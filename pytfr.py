#!/usr/bin/python
from bs4 import BeautifulSoup
import requests
from urllib.request import urlopen
from urllib.parse import urlencode
from io import BytesIO,StringIO
from zipfile import ZipFile
import json
import time
from pyshp import shapefile
from pyproj import Proj
from pyproj import transform
import pycrs
import datetime





class ArcServerLink(object):
    def __init__(self,portalUrl,userName,password):
        """This object is in charge of all interaction with the ArcGIS server that houses the TFR Data"""
        self.portal_url = portalUrl
        self.user_name = userName
        self.password = password
        self.token = ""
        self.token_expire_time = 0

        ## Important here that this variable below is the location of the layer that will be edited
        self.feature_add_location = "https://egp.nwcg.gov/arcgis/rest/services/FireCOP/TFRData/FeatureServer/0/addFeatures?"



        
    def generateToken(self):
        """This method is for getting a token to allow editing feature data on the arcgis server"""
        tokenURL = self.portal_url + "/arcgis/tokens/?request=gettoken&username=%s&password=%s&f=JSON" % (self.user_name,self.password)
        #tokenURL = 'https://egp.nwcg.gov/arcgis/tokens/?request=gettoken&username=pwingard&password=0464KMspe&f=JSON'

        response = urlopen(tokenURL).read()
        #print(response[0])
        
        responseJSON =  json.loads(response.decode('ascii'))
        #print(responseJSON)
        token = responseJSON.get('token')
        expire_time = responseJSON.get('expires')
        self.token = token
        self.token_expire_time = int(expire_time)
    def checkTokenExpiration(self):
        """This method checks the objects token to see if it exists and if it is currently valid. if not it automatically generates a new one"""
        
        if self.token != "":
            current_time = round(time.time())
            token_remaining = self.token_expire_time - current_time

            if token_remaining < 60:
                self.generateToken()

        else:

            self.generateToken()
    def addTFRShapefiles(self,TFRShapefileProcessor):
        """This method takes a list of TFRShapefiles and adds them to the ARcGIS Server"""
        # make sure there are actual objects to load
        # then delete all old TFRs
        if len(TFRShapefileProcessor.tfr_shapefile_list) > 20:
            self.checkTokenExpiration()
            durl = "https://egp.nwcg.gov/arcgis/rest/services/FireCOP/TFRData/FeatureServer/0/deleteFeatures?"
            dparams = urlencode({'token':self.token,'where':'OBJECTID > 0','f':'json'})
            dparams = dparams.encode('ascii')
            dresult = urlopen(durl,dparams).read()
            #print(json.loads(dresult))
            params = urlencode({'token' : self.token,
                                   'f' : 'json'})

            info=json.dumps(TFRShapefileProcessor.tfr_shapefile_list)
            payload = {'f':'json','features':info,'token':self.token}
            data = urlencode(payload)
            data = data.encode('ascii')
                    
            result = urlopen(self.feature_add_location, data).read()
            json_results = json.loads(result.decode('ascii'))
            return json_results
            #print(json_results)
            
            
        
class NotamInfo(object):
    def __init__(self,faaTfrUrl):
        """This object is for getting TFR information from the FAA website"""
        self.faa_tfr_url = faaTfrUrl
        
    def getCurrentTFRNotams(self):
        """Returns a list of zipped shapefile urls that are hosted on the FAA web server"""
        out_list = []
        burl = "https://pilotweb.nas.faa.gov/PilotWeb/noticesAction.do?queryType=ALLTFR&formatType=DOMESTIC"

        web_page = urlopen(burl)
        soup = BeautifulSoup(web_page)


        items = soup.findAll('div',id="notamRight")
        for text_block in items:
            small_block = text_block.find('b')
            out_block =  small_block.contents[0].replace('/','_')
            shapefile_url = "http://tfr.faa.gov/save_pages/" + out_block + ".shp.zip"
            if shapefile_url not in out_list:
                response = requests.get(shapefile_url)
                if response.status_code < 400:
                    out_list.append(shapefile_url)
        return out_list


class ShapefileRetriever(object):
    def __init__(self):
        """this object retrieves TFR shapefile information from a zipfile on the FAA server and places the information in memory"""
        self.name = 'TFRShapefileRetriever'

    def retrieve(self,url):
        """this method retrieves a zipped shapefile from the web and places the information into memory. the notam id parameter should be in a format like 7_3456"""
        pre_notam = ""
        notam_id = ""
        try:
            pre_notam = url.split('/')[-1]
            notam_id = pre_notam.split('.')[0]
        except ValueError:
            print('The URL provided was not valid: ' + url)
            
        url = urlopen(url)
        zipfile = ZipFile(BytesIO(url.read()))

        prjString = zipfile.open(notam_id + ".prj").read()
        prj_string = prjString.decode('ascii')

        shp = BytesIO(zipfile.open(notam_id + ".shp").read())
        dbf = BytesIO(zipfile.open(notam_id + ".dbf").read())
        prj = BytesIO(zipfile.open(notam_id + ".prj").read())
        shx = BytesIO(zipfile.open(notam_id + ".shx").read())

        tfr_shape = TFRShapefile(shp,dbf,prj,shx,prj_string)
        return tfr_shape

class TFRShapefile(object):
    def __init__(self,shp,dbf,prj,shx,prj_string):
        """This object contains in-memory information from a shapefile that is read from a compressed .zip file on the web"""
        self.shp = shp
        self.dbf = dbf
        self.prj = prj
        self.shx = shx
        self.prj_string = prj_string
    


class TFRShapefileProcessor(object):
    def __init__(self):
        """This class contains a list of TFRshapefile objects. It then processes those objects for use with ArcServer"""
        self.tfr_shapefile_list = []

    def processShapefile(self,tfrShapefile):
        """This method receives a shapefile and processes it to extract attribute/spatial information"""
        sf = shapefile.Reader(shp = tfrShapefile.shp,dbf=tfrShapefile.dbf,prj=tfrShapefile.prj,shx = tfrShapefile.shx)

        #below is the list of fields found in the FAA data.
        field_list = ["NOTAM_ID","TFR_TYPE","TFR_AREA","LOWER_ALT","LALT_TYPE","UPPER_ALT","UALT_TYPE","EFFECTIVE","SHAPE@"]
        shapeRecs = sf.shapeRecords()
        recCount = len(shapeRecs)
        fields = sf.fields
        for i in range(0,recCount):
            value_dict = {}
            value_dict['attributes'] = {}

            value_dict['geometry'] = {}
            value_dict['geometry']['rings'] = []
            
            prow = []
            recs = shapeRecs[0].record

            zcount = 0
            for r in recs:
                value_dict['attributes'][field_list[zcount]] = r
                zcount+=1

            notam = value_dict['attributes']['NOTAM_ID']
            webu = "http://tfr.faa.gov/save_pages/detail_" + notam.replace('/','_') + ".html"
            value_dict['attributes']['WebLink'] = webu
            coords = shapeRecs[i].shape.points
            for pt in coords:
                mycoords = self.convertCoordinates(pt[0],pt[1],tfrShapefile.prj_string,4269)
                
                lon,lat = mycoords[0],mycoords[1]
                prow.append([lon,lat])

            value_dict['geometry']['rings'].append(prow)

            value_dict['geometry']['spatialReference'] = {'wkid':4269}
            self.tfr_shapefile_list.append(value_dict)

    def convertCoordinates(self,inX,inY,inProjStr,outProjWKID):
        """This method converts the x/y values into something else. Needed because FAA shapefiles use differing coordinate systems"""

        fromcrs = pycrs.loader.parser.from_esri_wkt(inProjStr)
        proj_string = fromcrs.to_proj4()
        inProj = Proj(proj_string,preserve_units = True)
        outProj = Proj('+init=EPSG:' + str(outProjWKID))
        #outProj = Proj(proj='latlong',datum='WGS84')
        outp = transform(inProj,outProj,inX,inY)
        return outp
        
if __name__ == "__main__":
    tfrInfo = NotamInfo('"https://pilotweb.nas.faa.gov/PilotWeb/noticesAction.do?queryType=ALLTFR&formatType=DOMESTIC"')
    notamList = tfrInfo.getCurrentTFRNotams()
    sr = ShapefileRetriever()
    tfrProcessor = TFRShapefileProcessor()
    for notam in notamList:
        sfile = sr.retrieve(notam)
        tfrProcessor.processShapefile(sfile)


    aPortal = ArcServerLink("https://egp.nwcg.gov","USERNAME HERE","PASSWORD HERE")
    outp = aPortal.addTFRShapefiles(tfrProcessor)
    ff = open('dlog.txt','w')
    ff.write(str(outp))
    ff.close()
    bf = open('timestamp.txt','a')
    rstr = str(datetime.datetime.now())
    bf.write(rstr + "\n")
    bf.close()
    #a.checkTokenExpiration()
    #a.checkTokenExpiration()
    
    
    
