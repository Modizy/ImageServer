try:
    from PIL import Image
except ImportError:
    import Image

import os
import re
import sys
import time
import signal
import urllib
import logging
import httplib
import hashlib
import StringIO
import unicodedata

import tornado.web
import tornado.wsgi
import tornado.escape
from tornado.options import define, options

define("clusterInfos", default={}, help="url of img cluster", type=dict)
define(
    "signatureSecret", default="", help="add signature to request", type=str)
define("defaultQuality", default=90, help="default output quality", type=int)
define("minHeight", default=1, help="minimum height after resize", type=int)
define("maxHeight", default=2048, help="maximum height after resize", type=int)
define("minWidth", default=1, help="minimum width after resize", type=int)
define("maxWidth", default=2048, help="maximum width after resize", type=int)
define("timeoutGetCluster", default=2,
       help="timeout for get image on cluster", type=int)

define(
    "defaultCluster", default="", help="cluster used when no match", type=str)

define("maxRedirections", default=4, help="maximum of url redirection", type=int)
define("cacheControls", default={}, help="cache control header for the different clusters", type=dict)
define("defaultCacheControl", default="max-age=60*60", help="default cache control header", type=str)

options.parse_config_file('./conf/mpvip_server.conf') ## todo auto determine which conf to load ? 

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.DEBUG)

def removeAccents(s):
    """Removes all accents from the string"""
    if not s:
        return s
    if isinstance(s, str):
        s = unicode(s, "utf8", "replace")
    s = unicodedata.normalize('NFD', s)
    return s.encode('ascii', 'ignore')


for name in options.clusterInfos:
    if len(name) == 4:
        LOG.error(
            'You can\'t have a cluster name which have a length of 4, because it\'s in conflict with signature.')
        exit(1)

class PingTestHandler(tornado.web.RequestHandler):

    def get(self):
        self.set_status(200)
        return 

class ResizerHandler(tornado.web.RequestHandler):
    pilImage = None
    imgUrl = None
    useHttps = False
    cluster = None
    format = None
    crop = False
    fit = False
    quality = 90
    newHeight = 0
    newWidth = 0
    offsetX = 0
    offsetY = 0
    newWidth = 0
    originalWidth = 0
    originalHeight = 0

    def get(self, signature, cluster, crop_or_fit, quality, width, height, offsetXfake, offsetX, offsetYfake, offsetY, imgUrl):
        imgUrl = imgUrl.encode('utf8')
        LOG.debug("imgUrl before: %s" % imgUrl)
        imgUrl = urllib.quote(imgUrl)
        LOG.debug("imgUrl after: %s" % imgUrl)
        imgUrl = removeAccents(imgUrl)
        self.checkParams(
            signature, cluster, crop_or_fit, quality, width, height, offsetX, offsetY, imgUrl)
        self.loadImageFromCluster()
        LOG.debug("signature=%s, cluster=%s, crop_or_fit=%s, quality=%s, width=%s, height=%s, offsetXfake=%s, offsetX=%s,offsetYfake=%s, offsetY=%s, imgUrl=%s" % (signature, cluster, crop_or_fit, quality, width, height, offsetXfake, offsetX, offsetYfake, offsetY, imgUrl))

        if self.crop:
            cropRatio = float(self.newHeight) / self.newWidth
            ratio = float(self.originalHeight) / self.originalWidth

            if cropRatio < ratio:
                cropW = self.originalWidth
                cropH = int(self.originalWidth * cropRatio) or 1
            else:
                cropH = self.originalHeight
                cropW = int(self.originalHeight / cropRatio) or 1

            cropX = int(0.5 * (self.originalWidth - cropW)) + self.offsetX ## offset from the "middle"
            cropX = max(0, cropX) ## cant be negative
            cropX = min(self.originalWidth - cropW, cropX) ## we need to be sure that cropX + cropW <= self.originalWidth

            cropY = int(0.5 * (self.originalHeight - cropH)) + self.offsetY ## offset from the "middle"
            cropY = max(0, cropY) ## cant be negative
            cropY = min(self.originalHeight - cropH, cropY) ## we need to be sure that cropX + cropW <= self.originalWidth

            LOG.debug("ratio=%s, cropRatio=%s | originalWidth=%s, originalHeight=%s, offsetX=%s, offsetY=%s | cropW=%s, cropH=%s | cropX=%s, cropY=%s" % (ratio, cropRatio, self.originalWidth, self.originalHeight, self.offsetX, self.offsetY, cropW, cropH, cropX, cropY))

            self.cropImage(cropX, cropY, cropW, cropH)
            self.resizeImage()
        elif self.fit:
            fitRatio = float(self.newHeight) / self.newWidth
            ratio = float(self.originalHeight) / self.originalWidth
            if fitRatio > ratio:
                self.newHeight = int(self.newWidth * ratio) or 1
            else:
                self.newWidth = int(self.newHeight / ratio) or 1
            self.resizeImage()
        else:
            if self.newWidth + self.newHeight == 0:
                pass
            elif self.newWidth == self.originalWidth and self.newHeight == 0:
                pass
            elif self.newHeight == self.originalHeight and self.newWidth == 0:
                pass
            elif self.newWidth > 0 and self.newHeight == 0:
                ratio = float(self.newWidth) / self.originalWidth
                self.newHeight = int(ratio * self.originalHeight) or 1
                self.resizeImage()
            elif self.newHeight > 0 and self.newWidth == 0:
                ratio = float(self.newHeight) / self.originalHeight
                self.newWidth = int(ratio * self.originalWidth) or 1
                self.resizeImage()
            else:
                self.resizeImage()

        image = StringIO.StringIO()

        try:
            self.pilImage.save(image, self.format, quality=self.quality)
            self.set_header('Content-Type', 'image/' + self.format.lower())
            self.write(image.getvalue())
        except:
            msg = 'Finish Request Error {0}'.format(sys.exc_info()[1])
            LOG.error(msg)
            raise tornado.web.HTTPError(500, msg)

        cache_control = options.cacheControls.get(cluster, options.defaultCacheControl)
        self.set_header('Cache-Control', cache_control)

    def checkParams(self, signature, cluster, crop_or_fit, quality, width, height, offsetX, offsetY, imgUrl):
        self.imgUrl = '/' + imgUrl
        self.newHeight = int(height)
        self.newWidth = int(width)
        self.cluster = cluster
        if offsetX:
            self.offsetX = int(offsetX)
        if offsetY:
            self.offsetY = int(offsetY)

        if options.signatureSecret is not "" and (signature is None or signature[:4] != hashlib.sha512(options.signatureSecret + self.request.uri[5:]).hexdigest()[:4]):
            raise tornado.web.HTTPError(403, 'Bad signature')

        if self.cluster not in options.clusterInfos:
            raise tornado.web.HTTPError(
                400, 'Bad argument Cluster : cluster {0} not found in configuration'.format(self.cluster))

        if self.newHeight == 0 and self.newWidth == 0:
            raise tornado.web.HTTPError(
                400, 'Bad argument Height and Width can\'t be both at 0')

        if self.newHeight != 0:
            if self.newHeight < options.minHeight or self.newHeight > options.maxHeight:
                raise tornado.web.HTTPError(
                    400, 'Bad argument Height : {0}>=h<{1}'.format(options.minHeight, options.maxHeight))

        if self.newWidth != 0:
            if self.newWidth < options.minWidth or self.newWidth > options.maxWidth:
                raise tornado.web.HTTPError(
                    400, 'Bad argument Width : {0}>=w<{1}'.format(options.minWidth, options.maxWidth))

        if quality is not None:
            self.quality = int(re.match(r'\d+', quality).group())
        else:
            self.quality = options.defaultQuality

        if self.quality <= 0 or self.quality > 100:
            raise tornado.web.HTTPError(400, 'Bad argument Quality : 0>q<100')

        if crop_or_fit is not None:
            if crop_or_fit.startswith("crop"):
                self.crop = True
                if self.newWidth == 0 or self.newHeight == 0:
                    raise tornado.web.HTTPError(
                        400, 'Crop error, you have to sprecify both Width ({0}) and Height ({1})'.format(self.newWidth, self.newHeight))
            elif crop_or_fit.startswith("fit"):
                self.fit = True
                if self.newWidth == 0 or self.newHeight == 0:
                    raise tornado.web.HTTPError(
                        400, 'Fit error, you have to sprecify both Width ({0}) and Height ({1})'.format(self.newWidth, self.newHeight))
            else:
                raise tornado.web.HTTPError(
                        400, 'Error, {0} method not supported, use fit or crop'.format(crop_or_fit))

        return True


    def loadImageFromCluster(self, ttl=options.maxRedirections):
        if ttl<=0:
            raise tornado.web.HTTPError(
                    400, 'Too many redirections (> {0})'.format(options.maxRedirections))

        # is_redirection = ttl < options.maxRedirections
        # if is_redirection:
        #     link = httplib.HTTPConnection(self.host_of_redirection, timeout=options.timeoutGetCluster)
        # else:
        if self.cluster == "ext":
            ## imgUrl is an absolute url like /www.jaglever.com/wp-content/up... , splitting it
            self.domain_url = self.imgUrl[1:].split("/")[0]
            self.imgUrl = "/"+"/".join(self.imgUrl[1:].split("/")[1:])

        else:
            self.domain_url = options.clusterInfos.get(self.cluster)
        
        if self.useHttps:
            link = httplib.HTTPSConnection(self.domain_url, timeout=options.timeoutGetCluster)
        else:
            link = httplib.HTTPConnection(self.domain_url, timeout=options.timeoutGetCluster)

        link.request('GET', self.imgUrl)
        resp = link.getresponse()

        status = resp.status

        LOG.debug("Response for domain %s imgUrl %s --> status=%s  Content-Type=%s" % (self.domain_url, self.imgUrl, status, resp.getheader('Content-Type')))
        if status == httplib.FOUND or status == httplib.MOVED_PERMANENTLY:
            LOG.debug("resp.headers:%s" % resp.getheaders())
            location = resp.getheader("location")
            if location.lower().startswith("https"):
                self.useHttps = True
            else:
                self.useHttps = True
            full_url = location.replace("http://","").replace("https://","").replace("//","")
            LOG.debug("full_url:%s" % full_url)
            base_url = full_url.split("/")[0]
            LOG.debug("base_url:%s" % base_url)
            
            options.clusterInfos["redirection_cluster"] = base_url.split(":")[0]

            # new_cluster = None
            # for cluster_name, cluster_url in options.clusterInfos.iteritems():
            #     if cluster_url == base_url.split(":")[0]:
            #         new_cluster = cluster_name
            #         LOG.debug("matching cluster %s found" % new_cluster)
            #         break
            # if not new_cluster:
            #     if options.defaultCluster:
            #         LOG.warn("no matching cluster for base_url %s (url %s), using %s" % (base_url,full_url,options.defaultCluster))
            #         new_cluster = options.defaultCluster
            #     else:
            #         raise tornado.web.HTTPError(
            #         400, 'Bad Domain Name : {0}'.format(base_url))

            self.cluster = "redirection_cluster"
            self.imgUrl = "/"+"/".join(full_url.split("/")[1:])
            LOG.debug("new cluster %s (%s), new img url %s, ttl = %s" % (self.cluster,self.domain_url, self.imgUrl, ttl))

            return self.loadImageFromCluster(ttl=ttl-1)
        
        elif status == httplib.OK:
            content_type = resp.getheader('Content-Type')
            if content_type and content_type.startswith('image'):
                content = resp.read()
            else:
                raise tornado.web.HTTPError(
                    415, 'Bad Content type : {0}'.format(content_type))
        else:
            msg = 'Image not found on cluster {0} (imgUrl {1} ,status {2})'.format(self.cluster, self.imgUrl, status)
            LOG.error(msg)
            LOG.error("resp:%s" % resp)
            raise tornado.web.HTTPError(404, msg)

        link.close()
        content = StringIO.StringIO(content)

        try:
            self.pilImage = Image.open(content)
            self.pilImage.load()
        except:
            msg = 'Make PIL Image Error {0}'.format(sys.exc_info()[1])
            LOG.error(msg)
            raise tornado.web.HTTPError(415, msg)

        self.originalWidth, self.originalHeight = self.pilImage.size
        self.format = self.pilImage.format

        return True

    def resizeImage(self):
        try:
            newImg = self.pilImage.resize(
                (self.newWidth, self.newHeight), Image.ANTIALIAS)
        except:
            msg = 'Resize Error {0}'.format(sys.exc_info()[1])
            LOG.error(msg)
            raise tornado.web.HTTPError(500, msg)

        self.pilImage = newImg
        return True

    def cropImage(self, cropX, cropY, cropW, cropH):
        try:
            newImg = self.pilImage.crop(
                (cropX, cropY, (cropX + cropW), (cropY + cropH)))
        except:
            msg = 'Crop Error {0}'.format(sys.exc_info()[1])
            LOG.error(msg)
            raise tornado.web.HTTPError(500, msg)

        self.pilImage = newImg

    def write_error(self, status_code, **kwargs):
        if "exc_info" in kwargs:
            self.finish("<html><title>%(message)s</title>"
                        "<body>%(message)s</body></html>" % {
                            "message": tornado.escape.xhtml_escape(str(kwargs["exc_info"][1])),
                        })
        else:
            self.finish("<html><title>%(code)d: %(message)s</title>"
                        "<body>%(code)d: %(message)s</body></html>" % {
                            "code": status_code,
                            "message": httplib.responses[status_code],
                        })

tornadoapp = tornado.wsgi.WSGIApplication([
    (r"/test",
     PingTestHandler),
    (r"/([0-9a-zA-Z]{4}/)?([0-9a-zA-Z]+)/(crop/|fit/)?(\d+/)?(\d+)x(\d+)/(oX(\-?\d+)/)?(oY(\-?\d+)/)?(.+)",
     ResizerHandler),
    
])


def application(environ, start_response):
    if 'SCRIPT_NAME' in environ:
        del environ['SCRIPT_NAME']
    return tornadoapp(environ, start_response)
