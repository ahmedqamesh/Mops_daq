#pip install python-can
from __future__ import print_function
import time
import can
import numpy as np
bustype = ['socketcan',"pcan","ixxat","vector"]
channel = 'can0'
from analysis import controlServer
can.rc['interface'] = 'socketcan'
can.rc['channel'] = 'can0'
can.rc['bitrate'] = 125000
from can.interface import Bus
#bus = Bus()
def test():
    # Define parameters
    NodeIds = server.get_nodeIds()
    interface =server.get_interface()
    SDO_RX = 0x600
    index = 0x1000
    Byte0= cmd = 0x40 #Defines a read (reads data only from the node) dictionary object in CANOPN standard
    Byte1, Byte2 = index.to_bytes(2, 'little')
    Byte3 = subindex = 0 
    #write CAN message [read dictionary request from master to node]
    server.set_channelConnection(interface = interface)
    server.writeCanMessage(SDO_RX + NodeIds[0], [Byte0,Byte1,Byte2,Byte3,0,0,0,0], flag=0, timeout=30)
    
    #Response from the node to master
    cobid, data, dlc, flag, t = server.readCanMessages()
    print(f'ID: {cobid:03X}; Data: {data.hex()}, DLC: {dlc}')
    
    print('Writing example CAN Expedited read message ...')    
    #Example (1): get node Id
    VendorId = server.sdoRead(NodeIds[0], 0x1000,0,3000)
    print(f'VendorId: {VendorId:03X}')

    #Example (2): Read channels 
    n_channels = np.arange(3,35)
    c_subindices  = ["0","1","2","3","4","5","6","7","8","9","A","B","C","D","E","F",
                   "10","11","12","13","14","15","16","17","18","19","1A","1B","1C","1D","1E",
                   "20","21","22","23","24","25","26","27","28","29","2A","2B","2C","2D","2E","2F","30","31"]
    values = []
    for c_subindex in c_subindices: # Each i represents one channel
        c_index = 0x2200
        value = server.sdoRead(NodeIds[0], c_index,int(c_subindex,16),3000)
        values = np.append(values, value)
    n_channels = n_channels.tolist()
    for channel in n_channels:
        if values[n_channels.index(channel)] is not None:
            print("Channel %i = %0.3f "%(channel,values[n_channels.index(channel)]))
        else:
            print("Channel %i = %s "%(channel,"None"))
    server.stop()        

def producer(id, N = None):
    """:param id: Spam the bus with messages including the data id."""
    bus = can.interface.Bus(bustype=bustype[0], channel=channel, bitrate=125000)
    for i in range(N):
        msg = can.Message(arbitration_id= 0x601, data=[id, i, 16, 1, 0, 0, 0, 0], is_extended_id= False) 
        print(msg)
        #for msg in bus:
        #    print("{X}: {}".format(msg.arbitration_id, msg.data))
    
        #notifier = can.Notifier(bus, [can.Logger("recorded.log"), can.Printer()])
        try:
            bus.send(msg)
            print("Message sent on {}".format(bus.channel_info))
        except can.CanError:
            print("Message NOT sent")
        
        message = bus.recv(1.0)
        #listener(message)
        if message is None:
            print('Timeout occurred, no message.')
        else:
            cobid, data, dlc, flag, t = message.arbitration_id, message.data, message.dlc, message.is_extended_id, message.timestamp
            print(f'ID: {cobid:03X}; Data: {data.hex()}, DLC: {dlc}')

if __name__ == '__main__':   
    #producer(64, N = 2)
    server = controlServer.ControlServer(interface = "socketcan", set_channel =True)
    test()

    