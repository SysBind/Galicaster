# -*- coding:utf-8 -*-
# Galicaster, Multistream Recorder and Player
#
#       galicaster/recorder/utils
#
# Copyright (c) 2011, Teltek Video Research <galicaster@teltek.es>
#
# This work is licensed under the Creative Commons Attribution-
# NonCommercial-ShareAlike 3.0 Unported License. To view a copy of 
# this license, visit http://creativecommons.org/licenses/by-nc-sa/3.0/ 
# or send a letter to Creative Commons, 171 Second Street, Suite 300, 
# San Francisco, California, 94105, USA.

from gi.repository import Gst
import time
import thread

from galicaster.core import context

logger = context.get_logger()

class Switcher(Gst.Bin):

    def __init__(self, name, device, image=None, driver_type="v4lsrc", size=[1024,768], framerate="25/1"): 

        Gst.Bin.__init__(self, name)
        self.eph_error = False
        self.let_pass = False
        self.removing = False

        self.devicepath = device
        self.driver_type = driver_type

        # Create elements
        self.image = Gst.ElementFactory.make('videotestsrc', 'image')
        #for sending eos
        self.src1 = self.image


        self.device = Gst.ElementFactory.make(self.driver_type, 'device')
        scale = Gst.ElementFactory.make('videoscale') 
        rate  = Gst.ElementFactory.make('videorate') 
        self.selector = Gst.ElementFactory.make('input-selector', 'selector')
        q0 = Gst.ElementFactory.make('queue', 'q2branchimg')
        q1 = Gst.ElementFactory.make('queue', 'q2branchdev')
        q2 = Gst.ElementFactory.make('queue', 'q2device')
        qs = Gst.ElementFactory.make('queue', 'q2selector')
        self.identity = Gst.ElementFactory.make('identity', 'idprobe')

        caps_img = Gst.ElementFactory.make('capsfilter', 'capsimage')
        caps_dev = Gst.ElementFactory.make('capsfilter', 'capsdevice')
        caps_rate = Gst.ElementFactory.make('capsfilter', 'capsrate')
        caps_res = Gst.ElementFactory.make('capsfilter', 'capsres')
        text = Gst.ElementFactory.make('textoverlay', 'textimage')

        # Set properties
        self.device.set_property('device', device)
        self.image.set_property('is-live', True)
        self.image.set_property('pattern', "blue")
        text.set_property('text', "No VGA Signal")
        text.set_property('valignment', 1)
        text.set_property('font-desc', "arial,50px")

        q0.set_property('max-size-buffers', 1)
        q1.set_property('max-size-buffers', 1)
        q2.set_property('max-size-buffers', 1)
        qs.set_property('max-size-buffers', 1)

        rate.set_property('silent',True)
        scale.set_property('add-borders',True)


        # CAPS
        filtre_img = Gst.Caps.from_string(
            "video/x-raw-yuv,format=(fourcc)YUY2, width={0}, height={1}, framerate=(fraction){2}, pixel-aspect-ratio=(fraction)1/1".format(size[0],size[1], framerate))
        filtre_dev = Gst.Caps.from_string(
            "video/x-raw-yuv,format=(fourcc)YUY2, framerate=(fraction){0}, pixel-aspect-ratio=(fraction)1/1".format(framerate))
        filtre_rate = Gst.Caps.from_string("video/x-raw-yuv,framerate={0}, pixel-aspect-ratio=(fraction)1/1".format(framerate))
        filtre_resolution =Gst.Caps.from_string("video/x-raw-yuv, width={0}, height={1}, pixel-aspect-ratio=(fraction)1/1".format(size[0],size[1]))

        caps_img.set_property('caps', filtre_img) #device
        caps_dev.set_property('caps', filtre_dev) #device
        caps_rate.set_property('caps', filtre_rate)
        caps_res.set_property('caps', filtre_resolution)

        # Add elements
        self.add(self.image, caps_img, text, q0, 
                 self.device, self.identity, caps_dev, q2, scale, caps_res, rate, caps_rate, q1,
                 self.selector, qs)

        # Link elements and set ghostpad
        Gst.element_link_many(self.image, caps_img, text, q0)
        Gst.element_link_many(self.device, self.identity, caps_dev, q2, scale, caps_res, rate, caps_rate, q1)

        q0.link(self.selector)
        q1.link(self.selector)
        self.selector.link(qs)
        self.add_pad(Gst.GhostPad.new('src', qs.get_pad('src')))

        # Set active pad
        if self.checking():
            self.selector.set_property('active-pad', 
                                       self.selector.get_pad('sink1'))
        else:
            self.selector.set_property('active-pad', 
                                       self.selector.get_pad('sink0'))
            self.eph_error = True
            self.thread_id=thread.start_new_thread(self.polling_thread, ())
            self.device.set_state(Gst.State.NULL)
            self.remove(self.device)  #IDEA remove it when at NULL

      # Set probe
        pad = self.identity.get_static_pad("src")
        pad.add_event_probe(self.probe)
        
    def let_eos_pass(self):
        """
        Change the variable to let the final EOS event pass
        """
        self.let_pass = True

    def checking(self):
        pipe = Gst.Pipeline('check')
        device = Gst.ElementFactory.make(self.driver_type, 'check-device')
        device.set_property('device', self.devicepath)
        sink = Gst.ElementFactory.make('fakesink', 'fake')
        pipe.add(device, sink)
        device.link(sink)
        # run pipeline
        pipe.set_state(Gst.State.PAUSED)
        pipe.set_state(Gst.State.PLAYING)
        state = pipe.get_state()
        pipe.set_state(Gst.State.NULL)
        if state[0] != Gst.StateChangeReturn.FAILURE:
            return True
        return False

    def polling_thread(self):
        logger.debug("Initializing polling")
        thread_id = self.thread_id
        pipe = Gst.Pipeline('poll')
        device = Gst.ElementFactory.make(self.driver_type, 'polling-device')
        device.set_property('device', self.devicepath)
        sink = Gst.ElementFactory.make('fakesink', 'fake')
        pipe.add(device, sink)
        device.link(sink)
        bucle = 0
        while thread_id == self.thread_id:
            if self.removing:
                self.removing = False
                self.device.set_state(Gst.State.NULL)
                self.remove(self.device)
            pipe.set_state(Gst.State.PAUSED) # FIXME assert if a Gtk.gdk is neccesary
            pipe.set_state(Gst.State.PLAYING)
            state = pipe.get_state()
            if state[0] != Gst.StateChangeReturn.FAILURE:
                logger.debug("VGA active again")
                pipe.set_state(Gst.State.NULL)
                self.thread_id = None
                self.reset_vga()
            else:
                pipe.set_state(Gst.State.NULL)
                time.sleep(0.8)
            bucle += 1


    def probe(self, pad, event):        
        if not self.let_pass:
            if event.type == Gst.EVENT_EOS and not self.eph_error:
                logger.debug("EOS Received")
                self.switch("sink0")
                self.eph_error = True
                # self.device.set_state(Gst.State.NULL)
                self.thread_id = thread.start_new_thread(self.polling_thread,())
                logger.debug("Epiphan BROKEN: Switching Epiphan to Background")
                return False
            if event.type == Gst.EVENT_NEWSEGMENT and self.eph_error:
                logger.debug("NEW SEGMENT Received")
                
                self.switch("sink1")
                self.eph_error = False
                logger.debug('Epiphan RECOVERED: Switching back to Epiphan')
                return False # Sure about this?
        else:
            return True # the eos keeps going till the sink

    def switch(self, padname):
        logger.debug("Switching to: "+padname)
        self.selector.emit('block')
        newpad = self.selector.get_static_pad(padname)
        # start_time = newpad.get_property('running-time')
        self.selector.emit('switch', newpad, -1, -1)
        self.removing = True

    def switch2(self): # TODO review this function and delete if unnecessary
        padname = self.selector.get_property('active-pad').get_name()
        if padname == "sink0":
            newpad = self.selector.get_static_pad("sink1")
        else:
            newpad = self.selector.get_static_pad("sink0")

        self.selector.emit('block')            
        self.selector.emit('switch', newpad, -1, -1)

    def reset_vga(self):
        logger.debug("Resetting Epiphan")
        
        if self.get_by_name('device') != None :
            self.device.set_state(Gst.State.NULL) 
            self.remove(self.device)
        del self.device
        self.device = Gst.ElementFactory.make(self.driver_type, 'device')
        self.device.set_property('device', self.devicepath)
        self.add(self.device)
        self.device.link(self.identity)
        self.device.set_state(Gst.State.PLAYING)
        self.identity.get_state() 

    def reset2(self):
        self.device = Gst.ElementFactory.make(self.driver_type, 'device')
        self.device.set_property('device', self.devicepath)
        self.add(self.device)
        self.device.link(self.identity)
        self.device.set_state(Gst.State.PLAYING)
        self.identity.get_state()

    def send_event_to_src(self, event): # IDEA made a common for all our bins
        self.let_eos_pass()
        self.device.send_event(event)    
        self.src1.send_event(event)

        
def get_videosink(videosink='xvimagesink', name='gc-preview'):
    logger.debug("Video sink: {} -> {}".format(name, videosink))
    gcvsink = "xvimagesink sync=false async=false qos=true name={}".format(name)
    
    if videosink == "ximagesink":
        gcvsink = "ximagesink sync=false async=false qos=false name={}".format(name)
        
    elif videosink == "fpsdisplaysink":
        gcvsink = 'fpsdisplaysink name={}-fps async-handling=false qos=false video-sink="xvimagesink name={}"'.format(name, name)
        
    elif videosink == "autovideosink":
        gcvsink = "autovideosink name={} sync=false async=false".format(name)
        
    elif videosink == "fakesink":
        gcvsink = "fakesink async=false name={}".format(name)

    return gcvsink


def get_audiosink(audiosink='autoaudiosink', name='gc-apreview'):    
    logger.debug("Audio sink: {} -> {}".format(name, audiosink))
    gcasink = "autoaudiosink sync=false name={}".format(name)
    
    if audiosink == "alsasink":
        gcasink = "alsasink sync=false name={}".format(name)
        
    elif audiosink == "pulsesink":
        gcasink = "pulsesink sync=false name={}".format(name, name)
        
    elif audiosink == "fakesink":
        gcasink = "fakesink silent=true name={}".format(name)

    return gcasink
