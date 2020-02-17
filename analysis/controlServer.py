
from __future__ import annotations
from typing import *
import time
import sys
import os
from matplotlib.backends.backend_qt5agg import FigureCanvas
from matplotlib.backends.qt_compat import QtCore, QtWidgets
from PyQt5.QtCore    import *
from PyQt5.QtGui     import *
from PyQt5.QtWidgets import *
from pathlib import Path
from analysis import logger
import logging
from logging.handlers import RotatingFileHandler
from threading import Thread, Event, Lock
import matplotlib as mpl
import numpy as np
from graphics_Utils import dataMonitoring , menuWindow , childWindow ,logWindow, mainWindow
from analysis import analysis_utils , controlServer
from analysis import CANopenConstants as coc
# Third party modules
from collections import deque, Counter
import coloredlogs as cl
import ctypes as ct
import verboselogs
from canlib import canlib, Frame
import analib
rootdir = os.path.dirname(os.path.abspath(__file__)) # This is your Project Root Directory [ALTERNATIVE root = analysis_utils.get_project_root()]
#log = logger.setup_derived_logger('Control Server')
class ControlServer(object):
    def __init__(self, parent=None, 
                 config=None, interface= None,
                 bitrate =None, logdir = None,
                 console_loglevel=logging.INFO,
                 file_loglevel=logging.INFO,
                 channel =None,ipAddress =None, GUI = None,
                 logformat='%(asctime)s - %(levelname)s - %(message)s'):
       
        super(ControlServer, self).__init__() # super keyword to call its methods from a subclass:
        
        self.__cnt = Counter()
        # Initialize logger
        verboselogs.install()
        self.logger = logging.getLogger(__name__)
        """:obj:`~logging.Logger`: Main logger for this class"""
        self.logger.setLevel(logging.DEBUG)
        self.controller_logger = logging.getLogger('controller')
        self.controller_logger.setLevel(logging.WARNING)
        #log directory
        if logdir is None:
            logdir = os.path.join(rootdir, 'log')
            if not os.path.exists(logdir):
                    os.makedirs(logdir)
        ts = os.path.join(logdir, time.strftime('%Y-%m-%d_%H-%M-%S_controller_Server.'))
        self.__fh = RotatingFileHandler(ts + 'log', backupCount=10,
                                        maxBytes=10 * 1024 * 1024)
        fmt = logging.Formatter(logformat)
        fmt.default_msec_format = '%s.%03d'
        self.__fh.setFormatter(fmt)
        cl.install(fmt=logformat, level=console_loglevel, isatty=True,milliseconds=True)
        self.__fh.setLevel(file_loglevel)

        # Read configurations from a file
        self.logger.notice('Read configuration file ...')
        if config is None:
            conf = analysis_utils.open_yaml_file(file ="MoPS_daq_cfg.yml",directory =rootdir[:-8])
        
        #get info about the application
        self.__appName = conf['Application']['app_name']
        self.__version = conf['Application']['version']
        self.__interfaceItems =conf['Application']["interface_items"]
        
        # Interface (Default is AnaGate)
        if interface is None:
            interface = conf['CAN_Interface']['AnaGate']['name']           
        elif interface not in ['Kvaser', 'AnaGate']:
            raise ValueError(f'Possible CAN interfaces are "Kvaser" or '
                             f'"AnaGate" and not "{interface}".')
        self.__interface = interface
        self.logger.success('Setting the default interface to %s' %interface)
        
        """:obj:`int` : Internal attribute for the bit rate""" 
        if bitrate is None:
            bitrate = conf['CAN_Interface']['AnaGate']['bitrate']
        #bitrate = self._parseBitRate(bitrate)
               
        self.__bitrate = bitrate
        #ipAddress
        if ipAddress is None:
            ipAddress = conf['CAN_Interface']['AnaGate']['ipAddress']
        
        self.__ipAddress = ipAddress
        
        
        self.__ch = None 
        self.__busOn = False  

        """:obj:`int` : Internal attribute for the channel index"""
        if channel is None:
            channel = conf['CAN_Interface']['AnaGate']['channel']
        self.__channel = channel
        
        self.logger.success('Loading configurations is Done.....!')

        #Opening channel
        #self.start_channelConnection(interface = interface, ipAddress = ipAddress, channel = channel, baudrate = bitrate)

            
        """Internal attribute for the |CAN| channel"""
        self.logger.success(str(__name__))
        self.__busOn = True
        self.__canMsgQueue = deque([], 10)
        self.__pill2kill = Event()
        self.__lock = Lock()
        self.__kvaserLock = Lock()
              
        if GUI is not None:
            self.logger.notice('Opening a graphical user Interface')
            self.start_graphicalInterface()
        # Scan nodes
        self.__nodeIds = conf["CAN_settings"]["nodeIds"]
        """:obj:`list` of :obj:`int` : Contains all |CAN| nodeIds currently
        present on the bus."""    
        self.__myDCs = {}
        """:obj:`list` : |controller| Object representation of all |DCS| Controllers
        that are currently on the |CAN| bus"""
        self.__mypyDCs = {}
        """:obj:`dict` : List of :class:`MyDCSController` instances which
        mirrors |controller| adress space. Key is the node id."""
        self.__ADCTRIM = {}
        """:obj.`dict` : List of ADC trimming bits for each node id."""
         
    def start_graphicalInterface(self):
        qapp = QtWidgets.QApplication(sys.argv)
        app = mainWindow.MainWindow()
        app.Ui_ApplicationWindow()
        qapp.exec_()

    def _parseBitRate(self, bitrate):
        if self.__interface == 'Kvaser':
            if bitrate not in coc.CANLIB_BITRATES:
                raise ValueError(f'Bitrate {bitrate} not in list of allowed '
                                 f'values!')
            return coc.CANLIB_BITRATES[bitrate]
        else:
            if bitrate not in analib.constants.BAUDRATES:
                raise ValueError(f'Bitrate {bitrate} not in list of allowed '
                                 f'values!')
            return bitrate
    
    def start_channelConnection(self, interface = None, ipAddress = None, channel = None, baudrate= None): 
        self.logger.success("Connecting to %s Interface" %interface)
        if interface == 'Kvaser':
            self.__ch = canlib.openChannel(channel,canlib.canOPEN_ACCEPT_VIRTUAL)
        else:
            self.__ch = analib.Channel(ipAddress, channel, baudrate=baudrate)
        
    def set_canController(self, interface = None):
        if interface == 'Kvaser':
            self.__ch.setBusParams(self.__bitrate)
            self.logger.notice('Going in \'Bus On\' state ...')
            self.__ch.busOn()
            self.__canMsgThread = Thread(target=self.readCanMessages)
        else:
            self.__cbFunc = analib.wrapper.dll.CBFUNC(self._anagateCbFunc())
            self.__ch.setCallback(self.__cbFunc)
        
    #Setter and getter functions
    def set_interface(self, x):
        self.__interface = x
        self.get_interface()
        
    def set_nodeIds(self,x):
        self.__nodeIds =x
    
    def set_channel(self,x):
        self.__channel = x
    
    def set_ipAddress(self,x):
        self.__ipAddress = x
        
    def set_bitrate(self,x):
        self.__bitrate = x

    def get_appName(self):
        return self.__appName 
    
    def get_version(self):
        return self.__version
    
        
    def get_DllVersion(self):
        ret = analib.wrapper.dllInfo()
        return ret
    
    def get_nodeIds(self):
        return self.__nodeIds
    
    def get_channelState(self,channel):
        return channel.state
    
    def get_bitrate(self):
        return self.__bitrate

    def get_ipAddress(self):
        """:obj:`str` : Network address of the AnaGate partner. Only used for
        AnaGate CAN interfaces."""
        if self.__interface == 'Kvaser':
            raise AttributeError('You are using a Kvaser CAN interface!')
        return self.__ipAddress    

    def get_interface_items(self):
        return self.__interfaceItems
    
    def get_interface(self):
        """:obj:`str` : Vendor of the CAN interface. Possible values are
        ``'Kvaser'`` and ``'AnaGate'``."""
        #print(self.__interface)
        return self.__interface
    

    def get_channelNumber(self):
        """:obj:`int` : Number of the crurrently used |CAN| channel."""
        return self.__channel

    @property
    def lock(self):
        """:class:`~threading.Lock` : Lock object for accessing the incoming
        message queue :attr:`canMsgQueue`"""
        return self.__lock


    @property
    def canMsgQueue(self):
        """:class:`collections.deque` : Queue object holding incoming |CAN|
        messages. This class supports thread-safe adding and removing of
        elements but not thread-safe iterating. Therefore the designated
        :class:`~threading.Lock` object :attr:`lock` should be acquired before
        accessing it.

        The queue is initialized with a maxmimum length of ``1000`` elements
        to avoid memory problems although it is not expected to grow at all.

        This special class is used instead of the :class:`queue.Queue` class
        because it is iterable and fast."""
        return self.__canMsgQueue
    
    @property
    def kvaserLock(self):
        """:class:`~threading.Lock` : Lock object which should be acquired for
        performing read or write operations on the Kvaser |CAN| channel. It
        turned out that bad things can happen if that is not done."""
        return self.__kvaserLock

    @property
    def cnt(self):
        """:class:`~collections.Counter` : Counter holding information about
        quality of transmitting and receiving. Its contens are logged when the
        program ends."""
        return self.__cnt

    @property
    def pill2kill(self):
        """:class:`threading.Event` : Stop event for the message collecting
        method :meth:`readCanMessages`"""
        return self.__pill2kill
    
    #@property
    def channel(self):
        """Currently used |CAN| channel. The actual class depends on the used
        |CAN| interface."""
        return self.__ch
#     
#     @property
#     def bitRate(self):
#         """:obj:`int` : Currently used bit rate. When you try to change it
#         :func:`stop` will be called before."""
#         if self.__interface == 'Kvaser':
#             return self.__bitrate
#         else:
#             return self.__ch.baudrate
#     
#     @bitRate.setter
#     def bitRate(self, bitrate):
#         if self.__interface == 'Kvaser':
#             self.stop()
#             self.__bitrate = bitrate
#             self.start()
#         else:
#             self.__ch.baudrate = bitrate     

    def sdoRead(self, nodeId, index, subindex, timeout=100,MAX_DATABYTES=8):
        """Read an object via |SDO|
    
        Currently expedited and segmented transfer is supported by this method.
        The function will writing the dictionary request from the master to the node then read the response from the node to the master
        The user has to decide how to decode the data.
        
        Parameters
        ----------
        nodeId : :obj:`int`
            The id from the node to read from
        index : :obj:`int`
            The Object Dictionary index to read from
        subindex : :obj:`int`
            |OD| Subindex. Defaults to zero for single value entries.
        timeout : :obj:`int`, optional
            |SDO| timeout in milliseconds
    
        Returns
        -------
        :obj:`list` of :obj:`int`
            The data if was successfully read
        :data:`None`
            In case of errors
        """
        SDO_TX =0x580  
        SDO_RX = 0x600
        interface =self.__interface
        self.set_canController(interface=interface)
        if nodeId is None or index is None or subindex is None:
            return None
        self.cnt['SDO read total'] += 1
        cobid = SDO_RX + nodeId
        msg = [0 for i in range(MAX_DATABYTES)]
        msg[1], msg[2] = index.to_bytes(2, 'little')
        msg[3] = subindex
        msg[0] = 0x40
        try:
            self.__ch.write(cobid, msg)
        except CanGeneralError:
            self.cnt['SDO read request timeout'] += 1
            return None
        
        # Wait for response
        t0 = time.perf_counter()
        messageValid = False
        print("Reading the dictionary response from the node to the master")
        while time.perf_counter() - t0 < timeout / 1000:
            with self.__lock:
                for i, (cobid_ret, ret, dlc, flag, t) in \
                        zip(range(len(self.__canMsgQueue)),
                            self.__canMsgQueue):
                    messageValid = \
                        (dlc == 8 and cobid_ret == SDO_TX + nodeId
                         and ret[0] in [0x80, 0x43, 0x47, 0x4b, 0x4f, 0x42] and
                         int.from_bytes([ret[1], ret[2]], 'little') == index
                         and ret[3] == subindex)
                    if messageValid:
                        del self.__canMsgQueue[i]
                        break
            if messageValid:
                break
        else:
            self.cnt['SDO read response timeout'] += 1
            return None
        # Check command byte
        if ret[0] == 0x80:
            abort_code = int.from_bytes(ret[4:], 'little')
            self.cnt['SDO read abort'] += 1
            return None
        nDatabytes = 4 - ((ret[0] >> 2) & 0b11) if ret[0] != 0x42 else 4
        data = []
        for i in range(nDatabytes):
            data.append(ret[4 + i])
        return int.from_bytes(data, 'little')

    def writeCanMessage(self, cobid, msg, flag=0, timeout=None):
        """Combining writing functions for different |CAN| interfaces

        Parameters
        ----------
        cobid : :obj:`int`
            |CAN| identifier
        msg : :obj:`list` of :obj:`int` or :obj:`bytes`
            Data bytes
        flag : :obj:`int`, optional
            Message flag (|RTR|, etc.). Defaults to zero.
        timeout : :obj:`int`, optional
            |SDO| write timeout in milliseconds. When :data:`None` or not
            given an infinit timeout is used.
        """
        print(cobid, msg)
        if self.__interface == 'Kvaser':
            if timeout is None:
                timeout = 0xFFFFFFFF
            with self.__kvaserLock:
                self.__ch.writeWait(Frame(cobid, msg), timeout)
        else:
            if not self.__ch.deviceOpen:
                print(cobid, msg)
                self.logger.notice('Reopening AnaGate CAN interface')           
            self.__ch.write(cobid, msg, flag)

    def readCanMessages(self):
        """Read incoming |CAN| messages and store them in the queue
        :attr:`canMsgQueue`.

        This method runs an endless loop which can only be stopped by setting
        the :class:`~threading.Event` :attr:`pill2kill` and is therefore
        designed to be used as a :class:`~threading.Thread`.
        """
        self.logger.notice('Starting pulling of CAN messages')
        while not self.__pill2kill.is_set():
            try:
                if self.__interface == 'Kvaser':
                    with self.__kvaserLock:
                        frame = self.__ch.read()
                    cobid, data, dlc, flag, t = (frame.id, frame.data,
                                                 frame.dlc, frame.flags,
                                                 frame.timestamp)
                    if frame is None or (cobid == 0 and dlc == 0):
                        raise canlib.CanNoMsg
                else:
                    cobid, data, dlc, flag, t = self.__ch.getMessage()
                    return cobid, data, dlc, flag, t
                with self.__lock:
                    self.__canMsgQueue.appendleft((cobid, data, dlc, flag, t))
                self.dumpMessage(cobid, data, dlc, flag)
            except (canlib.CanNoMsg, analib.CanNoMsg):
                pass
  
    #The following functions are to read the can messages
    def _anagateCbFunc(self):
        """Wraps the callback function for AnaGate |CAN| interfaces. This is
        neccessary in order to have access to the instance attributes.

        The callback function is called asychronous but the instance attributes
        are accessed in a thread-safe way.

        Returns
        -------
        cbFunc
            Function pointer to the callback function
        """

        def cbFunc(cobid, data, dlc, flag, handle):
            """Callback function.

            Appends incoming messages to the message queue and logs them.

            Parameters
            ----------
            cobid : :obj:`int`
                |CAN| identifier
            data : :class:`~ctypes.c_char` :func:`~cytpes.POINTER`
                |CAN| data - max length 8. Is converted to :obj:`bytes` for
                internal treatment using :func:`~ctypes.string_at` function. It
                is not possible to just use :class:`~ctypes.c_char_p` instead
                because bytes containing zero would be interpreted as end of
                data.
            dlc : :obj:`int`
                Data Length Code
            flag : :obj:`int`
                Message flags
            handle : :obj:`int`
                Internal handle of the AnaGate channel. Just needed for the API
                class to work.
            """
            data = ct.string_at(data, dlc)
            t = time.time()
            with self.__lock:
                self.__canMsgQueue.appendleft((cobid, data, dlc, flag, t))
            self.dumpMessage(cobid, data, dlc, flag)
        return cbFunc
    
    def dumpMessage(self,cobid, msg, dlc, flag):
        """Dumps a CANopen message to the screen and log file
    
        Parameters
        ----------
        cobid : :obj:`int`
            |CAN| identifier
        msg : :obj:`bytes`
            |CAN| data - max length 8
        dlc : :obj:`int`
            Data Length Code
        flag : :obj:`int`
            Flags, a combination of the :const:`canMSG_xxx` and
            :const:`canMSGERR_xxx` values
        """
    
        if (flag & canlib.canMSG_ERROR_FRAME != 0):
            print("***ERROR FRAME RECEIVED***")
        else:
            msgstr = '{:3X} {:d}   '.format(cobid, dlc)
            for i in range(len(msg)):
                msgstr += '{:02x}  '.format(msg[i])
            msgstr += '    ' * (8 - len(msg))        
                                                  
if __name__ == "__main__":
    pass