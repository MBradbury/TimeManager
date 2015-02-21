__author__ = 'carolinux'

from timelayer import *
from timevectorlayer import TimeVectorLayer
from time_util import DEFAULT_FORMAT, datetime_to_epoch, timeval_to_epoch, epoch_to_str,UTC
from interpolation.interpolator import LinearInterpolator
import qgis_utils as qgs

from PyQt4.QtCore import *
from PyQt4.QtGui import *
from collections import defaultdict
from qgis.core import *


DEFAULT_ID = 0

# Ideas for extending
#TODO: Just points types? What about lines or polygon move?
#TODO: What about totimeattr? if not supported then disable in ui when interpolation checked

# Testing
#TODO: test with multiple points (traces) 1.
#TODO: Scenario where 2 layers (one with interpolation and one without) are added and restored 3.

# Essential functionality
#TODO Modify ctrl.restoreTimeLayers to be able to recreate a TimeVectorInterpolated layer 2.

# Cleaning up
#TODO delete logging msgs when done testing

class TimeVectorInterpolatedLayer(TimeVectorLayer):

    def isInterpolationEnabled(self):
        return True

    def __init__(self,settings, iface):
        TimeVectorLayer.__init__(self,settings,iface=iface)
        try:
            QgsMessageLog.logMessage("Creating time interpolated layer")
            try:
                import numpy as np
            except:
                raise Exception("Need to have numpy installed")

            if self.layer.geometryType() != QGis.Point:
                raise Exception("Want point geometry!")
            self.idAttribute = settings.idAttribute

            self.memLayer = QgsVectorLayer("Point?crs=epsg:4326&index=yes",
                                           "interpolated_points_for_{}".format(
                self.layer.name()), "memory")

            # adjust memLayer to have same crs and same color as original layer, only half transparent
            self.memLayer.setCrs(self.layer.crs())
            qgs.setLayerColor(self.memLayer, qgs.getLayerColor(self.layer))
            qgs.setLayerTransparency(self.memLayer,0.5)
            qgs.refreshSymbols(self.iface, self.memLayer)

            QgsMapLayerRegistry.instance().addMapLayer(self.memLayer)

            provider = self.getProvider()
            self.fromTimeAttributeIndex = provider.fieldNameIndex(self.fromTimeAttribute)
            self.toTimeAttributeIndex = provider.fieldNameIndex(self.toTimeAttribute)

            if self.hasIdAttribute():
                self.idAttributeIndex = provider.fieldNameIndex(self.idAttribute)
                self.uniqueIdValues = set(provider.uniqueValues(self.idAttributeIndex))
            else:
                self.uniqueIdValues = set([DEFAULT_ID])

            self.fromInterpolator = LinearInterpolator()

            features = self.layer.getFeatures(QgsFeatureRequest() )
            for feat in features:
                from_time = timeval_to_epoch(feat[self.fromTimeAttributeIndex])
                to_time = timeval_to_epoch(feat[self.fromTimeAttributeIndex])
                geom = feat.geometry()
                if geom.type()!=QGis.Point:
                    QgsMessageLog.logMessage("Ignoring 1 non-point geometry")
                    continue
                coords = (geom.asPoint().x(), geom.asPoint().y())
                id = DEFAULT_ID if not self.hasIdAttribute() else feat[self.idAttributeIndex]
                self.fromInterpolator.addIdEpochTuple(id, from_time, coords)

            self.fromInterpolator.sort()
            self.n=0
            self.previous_ids = set()
            QgsMessageLog.logMessage("Created layer successfully!")
        except Exception,e :
            raise InvalidTimeLayerError(e)


    def __del__(self):
        QgsMessageLog.logMessage("deleting time interpolated layer")
        QgsMapLayerRegistry.instance().removeMapLayer(self.memLayer.id())
        del self.memLayer


    def getIdAttribute(self):
        return self.idAttribute

    def hasIdAttribute(self):
        return self.idAttribute is not None and self.idAttribute!=""


    def getInterpolatedGeometries(self, start_epoch, end_epoch):
        # 1. Find current Ids shown
        idsInFrame = set()
        features = self.layer.getFeatures(QgsFeatureRequest() )
        for feat in features:
            id = DEFAULT_ID if not self.hasIdAttribute() else feat[self.idAttributeIndex]
            idsInFrame.add(id)

        idsNotInFrame = self.uniqueIdValues - idsInFrame
        if len(idsNotInFrame)==0:
            # all ids are present in the frame, no need to interpolate :)
            return []

        pts = []
        for id in idsNotInFrame:
            pt = self.fromInterpolator.getInterpolatedValue(id,start_epoch, end_epoch)
            pts.append(QgsPoint(*pt))
        # 3. return  points list
        return pts

    def _clearMemoryLayer(self):
        #FIXME unclear how to get the layer feat ids exactly, so range works for now
        res = self.memLayer.dataProvider().deleteFeatures(range(self.n+1))
        assert(res)
        self.memLayer.triggerRepaint()

    def setTimeRestriction(self, timePosition, timeFrame):
        TimeVectorLayer.setTimeRestriction(self, timePosition, timeFrame)

        start_epoch = datetime_to_epoch(self.getStartTime(timePosition, timeFrame))
        end_epoch =  datetime_to_epoch(self.getEndTime(timePosition, timeFrame))

        QgsMessageLog.logMessage("setTimeRestriction Called {} times".format(self.n))
        QgsMessageLog.logMessage("size of layer at {}:{}".format(start_epoch,
                                                                 self.memLayer.featureCount(),
                                                              ))

        geoms = self.getInterpolatedGeometries(start_epoch, end_epoch)
        #Add the geometries as features
        self._clearMemoryLayer()

        self.previous_ids = set()

        features = []
        for i,geom in enumerate(geoms):

            feature = QgsFeature(id = start_epoch+i)
            feature.setGeometry(QgsGeometry.fromPoint(geom))
            #feature.setAttributes([start_epoch+i])
            features.append(feature) # if no attributes, it will fail
            self.previous_ids.add(feature.id())
            self.n = self.n + 1

        QgsMessageLog.logMessage("add {}features:".format(len(features)))
        res = self.memLayer.dataProvider().addFeatures(features)
        assert(res)
        self.memLayer.triggerRepaint()


    def deleteTimeRestriction(self):
        TimeVectorLayer.deleteTimeRestriction(self)
        self._clearMemoryLayer()


    def getSaveString(self):
        saveString = TimeVectorLayer.getSaveString(self)
        #TODO encode more info for interpolated layer to allow restoring from save string
        return saveString
