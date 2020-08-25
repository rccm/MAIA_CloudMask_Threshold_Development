import numpy as np
import matplotlib.pyplot as plt
from pyhdf.SD import SD
from read_MODIS_02 import get_data
import h5py
import time


#.datasets for sd()
#.attributes for sd().fieldnames

# #grab data
# filename = '/Users/vllgsbr2/Desktop/MODIS_Training/Data/venezuela_08_21_18/MOD35_L2.A2018233.1545.061.2018234021557.hdf' #'/Users/vllgsbr2/Desktop/MODIS_Training/Data/toronto_09_05_18/MOD35_L2.A2018248.1630.061.2018249014414.hdf'
# SD_field_rawData = 2 #0,1,2
# fieldname = 'Cloud_Mask'
# data_SD = get_data(filename, fieldname, SD_field_rawData) #shape (byte, height, width) (6, 2030, 1354)

def get_bits_old(data, N):
    '''
    INPUT:
        data - 3d numpy array - from cloud mask
        N    - into           - which byte block to use
    RETURN:
        numpy array - of shape (6, 2030, 1354) 6 bytes
                      for every pixel in granule
    '''
    shape = np.shape(data)
    #Nth index for first dimension to work on 1st/6 bytes
    data_flat = np.reshape(data[N, :, :], (shape[1]*shape[2]))

    #save remiander and int division into lists
    #remainder is the bit, int division is for next step
    #shape = (2030*1354, 2)
    #divmod(x, y)	the pair (x // y, x % y)
    bit_index_0  = np.array([divmod(int(i), 2) for i in data_flat])
    bit_index_12 = np.array([divmod(int(i), 4) for i in bit_index_0[:, 0]])
    bit_index_3  = np.array([divmod(int(i), 2) for i in bit_index_12[:, 0]])
    bit_index_4  = np.array([divmod(int(i), 2) for i in bit_index_3[:, 0]])
    bit_index_5  = np.array([divmod(int(i), 2) for i in bit_index_4[:, 0]])
    bit_index_67 = np.array([[int(i)%4] for i in bit_index_5[:, 0]])

    #dump the division row, we don't need it (note div not saved for last bit)
    Cloud_Mask_Flag               = np.reshape(bit_index_0,  (shape[1], shape[2], 2))[:,:,1]
    Unobstructed_FOV_Quality_Flag = np.reshape(bit_index_12, (shape[1], shape[2], 2))[:,:,1]
    Day_Night_Flag                = np.reshape(bit_index_3,  (shape[1], shape[2], 2))[:,:,1]
    Sun_glint_Flag                = np.reshape(bit_index_4,  (shape[1], shape[2], 2))[:,:,1]
    Snow_Ice_Background_Flag      = np.reshape(bit_index_5,  (shape[1], shape[2], 2))[:,:,1]
    Land_Water_Flag               = np.reshape(bit_index_67, (shape[1], shape[2]))

    #return all bits
    return Cloud_Mask_Flag,\
           Unobstructed_FOV_Quality_Flag,\
           Day_Night_Flag,\
           Sun_glint_Flag,\
           Snow_Ice_Background_Flag,\
           Land_Water_Flag

def get_bits(data_SD, N, cMask_or_QualityAssur=True):
    '''
    INPUT:
          data_SD               - 3D numpy array  - cloud mask SD from HDF
          N                     - int             - byte to work on
          cMask_or_QualityAssur - boolean         - True for mask, False for QA
    RETURNS:
          numpy.bytes array of byte stack of shape 2030x1354
    '''
    shape = np.shape(data_SD)

    #convert MODIS 35 signed ints to unsigned ints
    #basically AND all values with 255 (2**8 - 1 for a byte) which makes sets
    #the first bit to 0 i.e. positive
    if cMask_or_QualityAssur:
        #this SDS has 10 bytes in axis 0
        data_unsigned = np.bitwise_and(data_SD[N, :, :], 0xff)
    else:
        #this SDS has 6 bytes in axis 2
        data_unsigned = np.bitwise_and(data_SD[:, :, N], 0xff)



    #type is int16, but unpackbits taks int8, so cast array
    #we want one byte representation so 8 bits -> uint8
    data_unsigned = data_unsigned.astype(np.uint8)

    #return numpy array of length 8 lists for every element of data_SD
    #this is now in binary. Note binary is read right to left, so bits
    #bit[0,1,2,3,4,5,6,7] is indexed with
    #idx[7,6,5,4,3,2,1,0]
    data_bits = np.unpackbits(data_unsigned)

    #reshape so each pixel has list of 8 bits representing an integer in axis 2
    if cMask_or_QualityAssur:
        data_bits = np.reshape(data_bits, (shape[1], shape[2], 8))
    else:
        data_bits = np.reshape(data_bits, (shape[0], shape[1], 8))

    return data_bits

def save_mod35(data, save_path):
    hf = h5py.File(save_path, 'w')
    hf.create_dataset('MOD_35_decoded', data=data)
    hf.close()

#save_mod35(data_SD_bit, '/Users/vllgsbr2/Desktop/MODIS_Training/Data/mod_35/MOD_35.h5')

#recover bit array
#shape = (2030, 1354, 8)
#data = np.array(h5py.File('/Users/vllgsbr2/Desktop/MODIS_Training/Data/mod_35/MOD_35.h5', 'r').get('MOD_35_decoded'))

def decode_byte_1(decoded_mod35_hdf):
    '''
    INPUT:
          decoded_mod35_hdf: - numpy array (2030, 1354, 8) - bit representation
                               of MOD_35
    RETURN:
          Cloud_Mask_Flag,
          new_Unobstructed_FOV_Quality_Flag,
          Day_Night_Flag,
          Sun_glint_Flag,
          Snow_Ice_Background_Flag,
          new_Land_Water_Flag
                           : - numpy array (6, 2030, 1354) - first 6 MOD_35
                                                             products from byte1

    '''
    data = decoded_mod35_hdf
    shape = np.shape(data)

    #Note binary is read right to left, so bits
    #bit[0,1,2,3,4,5,6,7] is indexed with
    #idx[7,6,5,4,3,2,1,0]

    #create empty arrays to fill later
    #binary 1 or 0 fill
    Cloud_Mask_Flag           = data[:,:, 7]
    Day_Night_Flag            = data[:,:, 4]
    Sun_glint_Flag            = data[:,:, 3]
    Snow_Ice_Background_Flag  = data[:,:, 2]

    #0,1,2,or 3 fill
    #cloudy, uncertain clear, probably clear, confident clear
    Unobstructed_FOV_Quality_Flag = data[:,:, 5:7]
    #find index of each cloud possibility
    #new list to stuff new laues into and still perform a good search
    new_Unobstructed_FOV_Quality_Flag = np.empty((shape[0], shape[1]))

    cloudy_index          = np.where((Unobstructed_FOV_Quality_Flag[:,:, 0]==0)\
                                   & (Unobstructed_FOV_Quality_Flag[:,:, 1]==0))
    uncertain_clear_index = np.where((Unobstructed_FOV_Quality_Flag[:,:, 0]==0)\
                                   & (Unobstructed_FOV_Quality_Flag[:,:, 1]==1))
    probably_clear_index  = np.where((Unobstructed_FOV_Quality_Flag[:,:, 0]==1)\
                                   & (Unobstructed_FOV_Quality_Flag[:,:, 1]==0))
    confident_clear_index = np.where((Unobstructed_FOV_Quality_Flag[:,:, 0]==1)\
                                   & (Unobstructed_FOV_Quality_Flag[:,:, 1]==1))

    new_Unobstructed_FOV_Quality_Flag[cloudy_index]          = 0
    new_Unobstructed_FOV_Quality_Flag[uncertain_clear_index] = 1
    new_Unobstructed_FOV_Quality_Flag[probably_clear_index]  = 2
    new_Unobstructed_FOV_Quality_Flag[confident_clear_index] = 3

    #water, coastal, desert, land
    Land_Water_Flag = data[:,:, 0:2]
    #find index of each land type possibility
    new_Land_Water_Flag = np.empty((shape[0], shape[1]))

    water_index   = np.where((Land_Water_Flag[:,:, 0]==0) & \
                             (Land_Water_Flag[:,:, 1]==0))
    coastal_index = np.where((Land_Water_Flag[:,:, 0]==0) & \
                             (Land_Water_Flag[:,:, 1]==1))
    desert_index  = np.where((Land_Water_Flag[:,:, 0]==1) & \
                             (Land_Water_Flag[:,:, 1]==0))
    land_index    = np.where((Land_Water_Flag[:,:, 0]==1) & \
                             (Land_Water_Flag[:,:, 1]==1))

    new_Land_Water_Flag[water_index]   = 0
    new_Land_Water_Flag[coastal_index] = 1
    new_Land_Water_Flag[desert_index]  = 2
    new_Land_Water_Flag[land_index]    = 3

    return Cloud_Mask_Flag,\
           new_Unobstructed_FOV_Quality_Flag,\
           Day_Night_Flag,\
           Sun_glint_Flag,\
           Snow_Ice_Background_Flag,\
           new_Land_Water_Flag


def decode_tests(data_SD_cloud_mask, filename_MOD_35):
    '''
    INPUT:
          data_SD_cloud_mask - numpy array (6,2030,1354) - SD from HDF of cloud
                                                        mask
          filename_MOD_35 - str                       - path to mod 35 file
    RETURN:
          5 cloud mask tests that are quality assured - numpy arrays
                                                        (2030, 1354)
          High_Cloud_Flag_1380nm,
          Cloud_Flag_Visible_Reflectance,
          Cloud_Flag_Visible_Ratio,
          Near_IR_Reflectance,
          Cloud_Flag_Spatial_Variability
          overall_cloud_mask

    '''

    def decode_Quality_Assurance(data_SD_Quality_Assurance):
        '''
        INPUT:
              data_SD_Quality_Assurance - numpy array (2030,1354,10) - HDF SD of QA
        RETURN:
              Quality assurance for 5 cloud mask tests and overall cloud mask
        '''
        byte_1 = get_bits(data_SD_Quality_Assurance, 0, \
                               cMask_or_QualityAssur=False)
        byte_3 = get_bits(data_SD_Quality_Assurance, 2, \
                               cMask_or_QualityAssur=False)
        byte_4 = get_bits(data_SD_Quality_Assurance, 3, \
                               cMask_or_QualityAssur=False)

        #Note binary is read right to left, so bits
        #bit[0,1,2,3,4,5,6,7] is indexed with
        #idx[7,6,5,4,3,2,1,0]

        QA_High_Cloud_Flag_1380nm         = byte_3[:,:, 0]
        QA_Cloud_Flag_Visible_Reflectance = byte_3[:,:, 4]
        QA_Cloud_Flag_Visible_Ratio       = byte_3[:,:, 5]
        QA_Near_IR_Reflectance            = byte_3[:,:, 6]
        QA_Cloud_Flag_Spatial_Variability = byte_4[:,:, 1]
        #0 not useful; 1 useful
        QA_Cloud_Mask_Flag                = byte_1[:,:, 7]


        return QA_High_Cloud_Flag_1380nm,\
               QA_Cloud_Flag_Visible_Reflectance,\
               QA_Cloud_Flag_Visible_Ratio,\
               QA_Near_IR_Reflectance,\
               QA_Cloud_Flag_Spatial_Variability,\
               QA_Cloud_Mask_Flag

    fieldname = 'Quality_Assurance'
    data_SD_Quality_Assurance = get_data(filename_MOD_35, fieldname, 2)
    #for bytes 1&3&4
    #0 not applied; 1 applied
    QA_High_Cloud_Flag_1380nm,\
    QA_Cloud_Flag_Visible_Reflectance,\
    QA_Cloud_Flag_Visible_Ratio,\
    QA_Near_IR_Reflectance,\
    QA_Cloud_Flag_Spatial_Variability,\
    QA_Cloud_Mask_Flag = decode_Quality_Assurance(data_SD_Quality_Assurance)

    #Note binary is read right to left, so bits
    #bit[0,1,2,3,4,5,6,7] is indexed with
    #idx[7,6,5,4,3,2,1,0]

    #get test flags; 0 cloud, 1 clear; byte 1, 0 not determined, 1 determined
    byte_1 = get_bits(data_SD_cloud_mask, 0)
    byte_3 = get_bits(data_SD_cloud_mask, 2)
    byte_4 = get_bits(data_SD_cloud_mask, 3)

    #byte 1, 2 and 3 from cloud mask SDS
    High_Cloud_Flag_1380nm         = byte_3[:,:, 0]
    Cloud_Flag_Visible_Reflectance = byte_3[:,:, 4]
    Cloud_Flag_Visible_Ratio       = byte_3[:,:, 5]
    Near_IR_Reflectance            = byte_3[:,:, 6]
    Cloud_Flag_Spatial_Variability = byte_4[:,:, 1]
    Cloud_Mask_Flag                = byte_1[:,:, 7]

    #find indices where test is not applied; set to fill val
    #0 cloudy, 1 clear
    fill_val = 2
    High_Cloud_Flag_1380nm[QA_High_Cloud_Flag_1380nm == 0]                 = fill_val
    Cloud_Flag_Visible_Reflectance[QA_Cloud_Flag_Visible_Reflectance == 0] = fill_val
    Cloud_Flag_Visible_Ratio[QA_Cloud_Flag_Visible_Ratio == 0]             = fill_val
    Near_IR_Reflectance[QA_Near_IR_Reflectance == 0]                       = fill_val
    Cloud_Flag_Spatial_Variability[QA_Cloud_Flag_Spatial_Variability == 0] = fill_val
    Cloud_Mask_Flag[QA_Cloud_Mask_Flag == 0]                               = fill_val

    return High_Cloud_Flag_1380nm        ,\
           Cloud_Flag_Visible_Reflectance,\
           Cloud_Flag_Visible_Ratio      ,\
           Near_IR_Reflectance           ,\
           Cloud_Flag_Spatial_Variability,\
           Cloud_Mask_Flag




if __name__ == '__main__':

    ############################################################################
    #speed test
    filename_MOD_35 = '/data/keeling/a/vllgsbr2/b/modis_data/toronto_PTA/MOD_35/MOD35_L2.A2017038.1715.061.2017312050207.hdf'
    data_SD         = get_data(filename_MOD_35, 'Cloud_Mask', 2)

    #cloud mask tests with QA
    #not applied is 2; 0 cloudy, 1 clear
    High_Cloud_Flag_1380nm        ,\
    Cloud_Flag_Visible_Reflectance,\
    Cloud_Flag_Visible_Ratio      ,\
    Near_IR_Reflectance           ,\
    Cloud_Flag_Spatial_Variability = decode_tests(data_SD, filename_MOD_35)



    # #cloud mask plot
    # #fast bit
    # start = time.time()
    # fast_bits = get_bits(data_SD, 0)
    # fast_bits = decode_byte_1(fast_bits)
    # print('---------- ', time.time()-start,' ---------')
    #
    # #############################################
    # #plot
    # import matplotlib.colors as matCol
    # from matplotlib.colors import ListedColormap
    # cmap=plt.cm.PiYG
    # cmap = ListedColormap(['white', 'green', 'blue','black'])
    # norm = matCol.BoundaryNorm(np.arange(0,5,1), cmap.N)
    # plt.imshow(fast_bits[1], cmap=cmap, norm=norm)
    # plt.imsave('/data/keeling/a/vllgsbr2/b/modis_data/toronto_PTA/test_cases/CloudMask_2017038.1715.png', fast_bits[1], cmap=cmap)
    # cbar = plt.colorbar()
    # cbar.set_ticks([0.5,1.5,2.5,3.5])
    # cbar.set_ticklabels(['cloudy', 'uncertain\nclear', \
    #                      'probably\nclear', 'confident\nclear'])
    # plt.title('MODIS Cloud Mask')
    # plt.xticks([])
    # plt.yticks([])
    #plt.show()
