'''
AUTHORS: Javier Villegas Bravo
         Yizhe Zhan,
         Guangyu Zhao,
         University of Illinois at Urbana-Champaign
         Department of Atmospheric Sciences
         Sept 2019
This is the MAIA L2 Cloud Mask algorithm
Reference doc: MAIA Level 2 Cloud Mask Algorithm Theoretical Basis JPL-103722
'''

import numpy as np
import sys
from fetch_MCM_input_data import *
import time
from svi_calculation import svi_calculation#svi_dynamic_size_input import svi_calculation


#define arbitrary shape for granule/orbit to process
shape = (1000,1000)

#quality check radiance*********************************************************
#section 3.2.1.3 and 3.3.2.1.2 (last paragraph)
def mark_bad_radiance(radiance, RDQI, Max_RDQI):
    """
    check radiance quality

    [Sections 3.2.1.3 and 3.3.2.1.2]
    Specify low-quality radiance data (RDQI larger than a prescribed value as
    defined in configuration file) and missing data (RDQI==3).
    These data are set to -998 and -999, respectively.

    Arguments:
        radiance {2D narray} -- contains MAIA radiance at any band
        RDQI {2D narray} -- same shape as radiance; contains radiance quality flag
        Max_RDQI {integer} -- from configuration file;
                              denotes minimum usable quality flag

    Returns:
        2D narray -- radiance array with fill values denoting unusable or missing data
    """

    radiance[(RDQI > Max_RDQI) & (RDQI < 3)] = -998
    #delete meaningless negative radiance without stepping on -999 fill val
    radiance[(radiance < 0) & (radiance > -998)] = -998
    radiance[RDQI == 3] = -999

    return radiance

#calculate ancillary datasets***************************************************

#convert radiances to Bi-Directional Reflectance Factor, BRF, referred to as 'R'
#section 3.3.1.2
def get_R(radiance, SZA, d, E_std_0b):
    """
    convert radiances to Bi-Directional Reflectance Factor, BRF, referred to as 'R'

    [Section 3.3.1.2]
    Convert spectral band radiances to BRF, based on the given solar zenith angle,
    earth sun distance, and the band weighted solar irradiance.

    Arguments:
        radiance {2D narray} -- contains MAIA radiance at any band
        SZA {2D narray} -- same shape as radiance; contains solar zenith angles in degrees
        d {float} -- earth sun distance in Astonomical Units(AU)
        E_std_0b {float} -- band weight solar irradiance at 1 AU,
                            corresponding to the radiance band

    Returns:
        2D narray -- BRF; same shape as radiance
    """
    #now filter out where cosSZA is too small with fill value
    invalid_cosSZA_idx = np.where(np.cos(np.deg2rad(SZA)) <= 0.01)
    radiance[invalid_cosSZA_idx] = -998

    #condition to not step on fill values when converting to BRF(R)
    valid_rad_idx = np.where(radiance >= 0.0)
    radiance[valid_rad_idx] = ((np.pi * radiance * d**2)\
                           / (np.cos(np.deg2rad(SZA)) * E_std_0b))[valid_rad_idx]
    #just assign R to the memory of radiance to highlight conversion
    R = radiance

    #pretend radiance is reflectance cause that is what I'll pass in for now
    #radiance[valid_rad_idx] = radiance[valid_rad_idx] / (np.cos(np.deg2rad(SZA))[valid_rad_idx])
    #R = radiance

    return R

#calculate sun-glint flag*******************************************************
#section 3.3.2.3
def get_sun_glint_mask(solarZenith, sensorZenith, solarAzimuth, sensorAzimuth,\
                       sun_glint_exclusion_angle, land_water_mask):
    """
    Calculate sun-glint flag.

    [Section 3.3.2.3]
    Sun-glint water pixels are set to 0;
    non-sun-glint water pixels and land pixels are set to 1.

    Arguments:
        solarZenith {2D narray} -- Solar zenith angle in degree
        sensorZenith {2D narray} -- MAIA zenith angle in degree
        solarAzimuth {2D narray} -- Solar azimuth angle in degree
        sensorAzimuth {2D narray} -- MAIA azimuth angle in degree
        sun_glint_exclusion_angle {float} -- maximum scattering angle (degree) for sun-glint
        land_water_mask {2D binary narray} -- specify the pixel is water (0) or land (1)

    Returns:
        2D binary narray -- sunglint mask over granule same shape as solarZenith
    """

    solarZenith               = np.deg2rad(solarZenith)
    sensorZenith              = np.deg2rad(sensorZenith)
    solarAzimuth              = np.deg2rad(solarAzimuth)
    sensorAzimuth             = np.deg2rad(sensorAzimuth)
    sun_glint_exclusion_angle = np.deg2rad(sun_glint_exclusion_angle)

    cos_theta_r = np.sin(sensorZenith) * np.sin(solarZenith) \
                * np.cos(sensorAzimuth - solarAzimuth - np.pi ) + np.cos(sensorZenith) \
                * np.cos(solarZenith)
    theta_r = np.arccos(cos_theta_r)

    sun_glint_idx = np.where((theta_r >= 0) & \
                             (theta_r <= sun_glint_exclusion_angle))
    no_sun_glint_idx = np.where(~((theta_r >= 0) & \
                                  (theta_r <= sun_glint_exclusion_angle)))
    theta_r[sun_glint_idx]    = 0
    theta_r[no_sun_glint_idx] = 1
    #turn off glint calculated over land
    theta_r[land_water_mask == 1] = 1

    sun_glint_mask = theta_r
    #import matplotlib.pyplot as plt
    #from matplotlib import cm
    #cmap = cm.get_cmap('PiYG', 15) 
    #plt.figure(5)
    #plt.imshow(sensorZenith,cmap=cmap)
    #plt.colorbar()
    #plt.show()
    return sun_glint_mask

#calculate observables**********************************************************
#section 3.3.2.1.2
#and band center wavelengths table 2 section 2.1
#R_NIR -> bands 9, 12, 13 -> 0.86, 1.61, 1.88 micrometers
#RGB channels -> bands 6, 5, 4, respectively

#whiteness index
def get_whiteness_index(R_band_6, R_band_5, R_band_4):
    """
    calculate whiteness index

    [Section 3.3.2.1.2]
    whiteness index (WI) uses 3 MAIA spectral bands (4, 5, 6).

    Arguments:
        R_band_6 {2D narray} -- BRF narray for band 6
        R_band_5 {2D narray} -- BRF narray for band 5
        R_band_4 {2D narray} -- BRF narray for band 4

    Returns:
        2D narray -- whiteness index same shape as input arrays
    """

    #data quality house keeping to retain fill values
    whiteness_index = np.ones(np.shape(R_band_6)) * -998
    whiteness_index[(R_band_6 == -999) | (R_band_5 == -999) | (R_band_4 == -999)] = -999
    valid_data_idx = np.where((R_band_6 >= 0) & (R_band_5 >= 0) & (R_band_4 >= 0))

    #calc WI
    visible_average = (R_band_6 + R_band_5 + R_band_4)/3
    whiteness_index[valid_data_idx] = \
            (np.abs(R_band_6 - visible_average)/visible_average + \
             np.abs(R_band_5 - visible_average)/visible_average + \
             np.abs(R_band_4 - visible_average)/visible_average)[valid_data_idx]

    return whiteness_index

#normalized difference vegetation index
def get_NDVI(R_band_6, R_band_9):
    """
    calculate normalized difference vegetation index (NDVI)

    [Section 3.3.2.1.2]
    NDVI uses 2 MAIA spectral bands (6 and 9).

    Arguments:
        R_band_6 {2D narray} -- BRF narray for band 6
        R_band_9 {2D narray} -- BRF narray for band 9

    Returns:
        2D narray -- NDVI same shape as any BRF input
    """

    #data quality house keeping to retain fill values
    NDVI = np.ones(np.shape(R_band_6)) * -998
    NDVI[(R_band_6 == -999) | (R_band_9 == -999)] = -999
    valid_data_idx = np.where((R_band_6 >= 0) & (R_band_9 >= 0))

    NDVI[valid_data_idx] = \
                         ((R_band_9 - R_band_6) / (R_band_9 + R_band_6))[valid_data_idx]

    return NDVI

#normalized difference snow index
def get_NDSI(R_band_5, R_band_12):
    """
    calculate normalized difference snow index (NDVI)

    [Section 3.3.2.1.2]
    NDVI uses 2 MAIA spectral bands (5 and 12).

    Arguments:
        R_band_5 {2D narray} -- BRF narray for band 5
        R_band_12 {2D narray} -- BRF narray for band 12

    Returns:
        2D narray -- NDSI same shape as any BRF input
    """
    #data quality house keeping to retain fill values
    NDSI = np.ones(np.shape(R_band_5)) * -998
    NDSI[(R_band_5 == -999) | (R_band_12 == -999)] = -999
    valid_data_idx = np.where((R_band_5 >= 0) & (R_band_12 >= 0))

    NDSI[valid_data_idx] = \
                         ((R_band_5 - R_band_12) / (R_band_5 + R_band_12))[valid_data_idx]

    return NDSI

#visible reflectance
def get_visible_reflectance(R_band_6):
    """
    return visible BRF of 0.64 um spectral band

    [Section 3.3.2.1.2]
    As the reflectance of band 6 has already been calculated, nothing more will be done.

    Arguments:
        R_band_6 {2D narray} -- BRF narray for band 6

    Returns:
        2D narray -- same as BRF input
    """
    return R_band_6

#near infra-red reflectance
def get_NIR_reflectance(R_band_9):
    """
    return NIR BRF of 0.86 um spectral band

    [Section 3.3.2.1.2]
    As the reflectance of band 9 has already been calculated, nothing more will be done.

    Arguments:
        R_band_9 {2D narray} -- BRF narray for band 9

    Returns:
        2D narray -- same as BRF input
    """
    return R_band_9

#spatial variability index
def get_spatial_variability_index(R_band_6, numrows, numcols):
    """
    calculate spatial variability index (SVI)

    [Section 3.3.2.1.2]
    SVI for a pixel is calculated as the standard deviation of aggregated 1-km R_0.64
    within a 3X3 matrix centered at the pixel.

    Arguments:
        R_band_6 {2D narray} -- BRF narray for band 6

    Returns:
        2D narray -- SVI array with the shape same as BRF input
    """


    #make copy to not modify original memory
    R_band_6_ = np.copy(R_band_6)
    R_band_6_[R_band_6_ == -998] = -999
    bad_value = -999
    min_valid_pixels = 9
    spatial_variability_index = \
                            svi_calculation(R_band_6_, bad_value, min_valid_pixels)

    #data quality house keeping
    spatial_variability_index[R_band_6 == -998] = -998
    spatial_variability_index[R_band_6 == -999] = -999

    return spatial_variability_index

#cirrus test
def get_cirrus_Ref(R_band_13):
    """
    return NIR BRF of 1.88 um spectral band

    [Section 3.3.2.1.2]
    As the reflectance of band 13 has already been calculated, nothing more will be done.

    Arguments:
        R_band_13 {2D narray} -- BRF narray for band 13

    Returns:
        2D narray -- same as BRF input
    """
    return R_band_13

#calculate bins of each pixel to query the threshold database*******************

def get_observable_level_parameter(SZA, VZA, SAA, VAA, Target_Area,\
          land_water_mask, snow_ice_mask, sfc_ID, DOY, sun_glint_mask):

    """
    calculate bins of each pixel to query the threshold database

    [Section 3.3.2.2]

    Arguments:
        SZA {2D narray} -- solar zenith angle in degrees
        VZA {2D narray} -- viewing (MAIA) zenith angle in degrees
        SAA {2D narray} -- solar azimuth angle in degrees
        VAA {2D narray} -- viewing (MAIA) azimuth angle in degrees
        Target_Area {integer} -- number assigned to target area
        land_water_mask {2D narray} -- land (1) water(0)
        snow_ice_mask {2D narray} -- no snow/ice (1) snow/ice (0)
        sfc_ID {3D narray} -- surface ID anicillary dataset for target area
        DOY {integer} -- day of year in julian calendar
        sun_glint_mask {2D narray} -- no glint (1) sunglint (0)

    Returns:
        3D narray -- 3rd axis contains 9 integers that act as indicies to query
                     the threshold database for every observable level parameter.
                     The 1st and 2cnd axies are the size of the MAIA granule.
    """
    
    #This is used todetermine if the test should be applied over a particular
    #surface type in the get_test_determination function

    #define relative azimuth angle, RAZ, and cos(SZA)
    RAZ = VAA - SAA
    RAZ[RAZ<0] = RAZ[RAZ<0]*-1
    RAZ[RAZ > 180.] = -1 * RAZ[RAZ > 180.] + 360. #symmtery about principle plane
    cos_SZA = np.cos(np.deg2rad(SZA))

    #bin each input, then dstack them. return this result
    #define bins for each input
    bin_cos_SZA = np.arange(0.1, 1.1 , 0.1)
    bin_VZA     = np.arange(5. , 75. , 5.) #start at 5.0 to 0-index bin left of 5.0
    bin_RAZ     = np.arange(15., 195., 15.)
    bin_DOY     = np.arange(8. , 376., 8.0)

    binned_cos_SZA = np.digitize(cos_SZA, bin_cos_SZA, right=True)
    binned_VZA     = np.digitize(VZA    , bin_VZA, right=True)
    binned_RAZ     = np.digitize(RAZ    , bin_RAZ, right=True)
    binned_DOY     = np.digitize(DOY    , bin_DOY, right=True)
    #only have one day rn
    #sfc_ID         = sfc_ID[:,:,binned_DOY] #just choose the day for sfc_ID map

    #these datafields' raw values serve as the bins, so no modification needed:
    #Target_Area, land_water_mask, snow_ice_mask, sun_glint_mask, sfc_ID

    #put into array form to serve the whole space
    binned_DOY  = np.ones(shape) * binned_DOY
    Target_Area = np.ones(shape) * Target_Area

    observable_level_parameter = np.dstack((binned_cos_SZA ,\
                                            binned_VZA     ,\
                                            binned_RAZ     ,\
                                            Target_Area    ,\
                                            land_water_mask,\
                                            snow_ice_mask  ,\
                                            sfc_ID         ,\
                                            binned_DOY     ,\
                                            sun_glint_mask))

    missing_idx = np.where(SZA==-999)
    observable_level_parameter[missing_idx[0], missing_idx[1], :] = -999

    observable_level_parameter = observable_level_parameter.astype(dtype=np.int)
    #import matplotlib.pyplot as plt
    #from matplotlib import cm
    #cmap = cm.get_cmap('PiYG', 15)
    #plt.figure(4)
    #plt.imshow(binned_VZA,cmap=cmap)
    #plt.colorbar()

    return observable_level_parameter

#apply fill values to observables***********************************************
#section 3.3.2.4 in ATBD
#Using the observable level parameter (threshold bins)
#(cos_SZA, VZA, RAZ, Target Area, land_water, snowice, sfc_ID, DOY, sun_glint)
#Works on one observable at a time => function can be parallelized
#the function should return the threshold to be used for each of 5 tests at
#each pixel

#fill values
# -125 -> not applied due to surface type
# -126 -> low quality radiance
# -127 -> no data

def make_sceneID(observable_level_parameter,land_water_bins,\
                     sun_glint_bins, snow_ice_bins):

        """
        helper function to combine water/sunglint/snow-ice mask/sfc_ID into
        one mask. This way the threhsolds can be retrieved with less queries.

        [Section N/A]

        Arguments:
            observable_level_parameter {3D narray} -- return from func get_observable_level_parameter()
            land_water_bins {2D narray} -- land (1) water(0)
            sun_glint_bins {2D narray} -- no glint (1) sunglint (0)
            snow_ice_bins {2D narray} -- no snow/ice (1) snow/ice (0)

        Returns:
            2D narray -- scene ID. Values 0-28 inclusive are land types; values
                         29, 30, 31 are water, water with sun glint, snow/ice
                         respectively. Is the size of the granule. These integers
                         serve as the indicies to select a threshold based off
                         surface type.

        """

        #over lay water/glint/snow_ice onto sfc_ID to create a scene_type_identifier
        sfc_ID_bins = observable_level_parameter[:,:,6]
        scene_type_identifier = sfc_ID_bins

        scene_type_identifier[land_water_bins == 0]     = 12
        scene_type_identifier[(sun_glint_bins == 0) & \
                              (land_water_bins == 0)]   = 13
        scene_type_identifier[snow_ice_bins == 0]       = 14

        return scene_type_identifier


def get_test_determination(observable_level_parameter, observable_data,\
       threshold_path, observable_name, fill_val_1, fill_val_2, fill_val_3):

    """
    applies fill values to & finds the threshold needed at each pixel for
    for a given observable_data.

    [Section 3.3.2.4]

    Arguments:
       observable_level_parameter {3D narray} -- return from func get_observable_level_parameter()
       observable_data {2D narray} -- takes one observable at a time
       threshold_path {string} -- file path to thresholds
       observable_name {string} -- VIS_Ref, NIR_Ref, WI, NDVI, NDSI, SVI, Cirrus
       fill_val_1 {integer} -- defined in congifg file; not applied due to surface type
       fill_val_2 {integer} -- defined in congifg file; low quality radiance
       fill_val_3 {integer} -- defined in congifg file; no data

    Returns:
       2D narray -- observable_data with fill values applied
       2D narray -- the threshold needed at each pixel for that observable

    """
    observable_data[observable_data == -998] = fill_val_2
    observable_data[observable_data == -999] = fill_val_3

    land_water_bins = observable_level_parameter[:,:,4]
    snow_ice_bins   = observable_level_parameter[:,:,5]
    sun_glint_bins  = observable_level_parameter[:,:,8]

    #apply fill values according to input observable and surface type
    if observable_name == 'VIS_Ref':
        #where water or snow/ice occur this test is not applied
        observable_data[((land_water_bins == 0) | (snow_ice_bins == 0)) &     \
                        ((observable_data != fill_val_2) &                    \
                         (observable_data != fill_val_3)) ] = fill_val_1

    elif observable_name == 'NIR_Ref':
        #where land/sunglint/snow_ice occur this test is not applied
        observable_data[((sun_glint_bins  == 0)  | \
                         (land_water_bins == 1)  | \
                         (snow_ice_bins   == 0)) & \
                        ((observable_data != fill_val_2) & \
                         (observable_data != fill_val_3))]    = fill_val_1

    elif observable_name == 'WI':
        #where sunglint/snow_ice occur this test is not applied
        observable_data[((sun_glint_bins == 0)           |  \
                         (snow_ice_bins  == 0))          &  \
                        ((observable_data != fill_val_2) &  \
                         (observable_data != fill_val_3)) ]    = fill_val_1

    elif observable_name == 'NDVI':
        #where snow_ice occurs this test is not applied
        observable_data[(snow_ice_bins == 0)             &  \
                       ((observable_data != fill_val_2)  &  \
                        (observable_data != fill_val_3)) ]    = fill_val_1

    elif observable_name == 'NDSI':
        #where snow_ice do not occur this test is not applied
        observable_data[(snow_ice_bins == 1)             &  \
                        ((observable_data != fill_val_2) &  \
                         (observable_data != fill_val_3)) ]    = fill_val_1
    else:
        pass

    #Now we need to get the threshold for each pixel for one observable;
    #therefore, final return should be shape (X,Y) w/thresholds stored inside
    #and the observable_data with fill values added
    #these 2 will feed into the DTT methods

    #observable_level_parameter contains bins to query threshold database
    rows, cols = np.arange(shape[0]), np.arange(shape[1])

    #combine water/sunglint/snow-ice mask/sfc_ID into one mask
    #This way the threhsolds can be retrieved with less queries
    scene_type_identifier = make_sceneID(observable_level_parameter,land_water_bins,\
                     sun_glint_bins, snow_ice_bins)

    #because scene_type_identifier (sfc_ID) contains information on
    #sunglint/snow_ice/water/land we use less dimensions to decribe the scene
    OLP = np.zeros((1000,1000,6))
    OLP[:,:,:4] = observable_level_parameter[:,:,:4]#cosSZA, VZA, RAZ, TA
    OLP[:,:,4]  = scene_type_identifier             #scene_ID
    OLP[:,:,5] = observable_level_parameter[:,:,7]  #DOY

    #pick threshold for each pixel in 1000x1000 grid
    with h5py.File('/data/keeling/a/vllgsbr2/c/old_MAIA_Threshold_dev/LA_PTA_MODIS_Data/try2_database/thresholds_reproduce.hdf5', 'r') as hf_thresholds:
        OLP = OLP.reshape((1000**2, 6)).astype(dtype=np.int)
        #DOY and TA is same for all pixels in granule
        if not(np.all(OLP[:,3] == -999)) and not(np.all(OLP[:,5] == -999)):
            #not -999 index; use to define target area and day of year for the granule
            not_fillVal_idx = np.where(OLP[:,3]!=-999)
            TA = OLP[not_fillVal_idx[0], 3][0]
            DOY = OLP[not_fillVal_idx[0], 5][0]

            #put 0 index where is equal to -999
            #then we will go back and mask the retireved thresholds here as -999
            fillVal_idx = np.where(OLP==-999)
            OLP[fillVal_idx] = 0

        #if OLP[0,3]!=-999 or OLP[0,5]!=-999:
            #TA, DOY = OLP[0,3], OLP[0,5]
            path = 'TA_bin_{:02d}/DOY_bin_{:02d}/{}'.format(TA, DOY, observable_name)
            #print(path)

            database = hf_thresholds[path][()]
            thresholds =np.array([database[olp[0], olp[1], olp[2], olp[4]] for olp in OLP])
            #thresholds =[database[olp[0], olp[1], olp[2], olp[4]] if np.all(olp!=-999) else -999 for olp in OLP]
            #thresholds =[database[olp[0], olp[1], olp[2], olp[4]] for olp in OLP]

            thresholds[fillVal_idx[0]] = -999
            
            thresholds = np.array(thresholds).reshape((1000,1000))
            #print(thresholds)


            return observable_data, thresholds

        return observable_data, np.ones((1000,1000))*-999

#calculate distance to threshold************************************************
#keep fill values unchanged
#all DTT functions take thresholds and corresponding observable with fill values
#both 2D arrays of the same shape

#get_DTT_Ref_Test() also works for SVI & Cirrus
def get_DTT_Ref_Test(T, Ref, Max_valid_DTT, Min_valid_DTT, fill_val_1,\
                                                        fill_val_2, fill_val_3):

    """
    calculate the distance to threshold metric. This function is valid for
    both near infra-red and for visible reflectance test, as well as for
    spatial variability and cirrus tests.

    [Section 3.3.2.5]

    Arguments:
        T {2D narray} -- Thresholds for observable
        Ref {2D narray} -- observable; choose from vis ref, NIR ref, SVI, or Cirrus
        Max_valid_DTT {float} -- from configuration file; upper bound of DTT
        Min_valid_DTT {float} -- from configuration file; lower bound of DTT
        fill_val_1 {integer} -- defined in congifg file; not applied due to surface type
        fill_val_2 {integer} -- defined in congifg file; low quality radiance
        fill_val_3 {integer} -- defined in congifg file; no data

    Returns:
        2D narray -- Distance to threshold calculated for one observable over
                     the whole space.

    """

    #max fill value of three negative fill values to know what data is valid
    max_fill_val = np.max(np.array([fill_val_1, fill_val_2, fill_val_3]))

    DTT = np.copy(Ref)
    DTT[Ref > max_fill_val] = (100 * (Ref - T) / T)[Ref > max_fill_val]
    #put upper bound on DTT (fill vals all negative)
    DTT[DTT > Max_valid_DTT]  = Max_valid_DTT
    #put lower bound on DTT where observable is valid (fill vals all negative)
    DTT[(DTT < Min_valid_DTT) & (Ref > max_fill_val)] = Min_valid_DTT

    #where T is -999 we should give a no retreival fill value (fill_val_3 = -127)
    DTT[T==-999] = fill_val_3

    return DTT

def get_DTT_NDxI_Test(T, NDxI, Max_valid_DTT, Min_valid_DTT, fill_val_1,\
                                                        fill_val_2, fill_val_3):
    """
    calculate the distance to threshold metric. This function is valid for
    both near infra-red and for visible reflectance test, as well as for
    spatial variability and cirrus tests.

    [Section 3.3.2.6]

    Arguments:
        T {2D narray} -- Thresholds for observable
        Ref {2D narray} -- observable; choose from NDVI, NDSI
        Max_valid_DTT {float} -- from configuration file; upper bound of DTT
        Min_valid_DTT {float} -- from configuration file; lower bound of DTT
        fill_val_1 {integer} -- defined in congifg file; not applied due to surface type
        fill_val_2 {integer} -- defined in congifg file; low quality radiance
        fill_val_3 {integer} -- defined in congifg file; no data

    Returns:
        2D narray -- Distance to threshold calculated for one observable over
                     the whole space.

    """

    max_fill_val = np.max(np.array([fill_val_1, fill_val_2, fill_val_3]))

    DTT = np.copy(NDxI)
    T[T==0] = 1e-3
    DTT[NDxI > max_fill_val] = (100 * (T - np.abs(NDxI)) / T)[NDxI > max_fill_val]
    #put upper bound on DTT (fill vals all negative)
    DTT[DTT > Max_valid_DTT]  = Max_valid_DTT
    #put lower bound on DTT where observable is valid (fill vals all negative)
    DTT[(DTT < Min_valid_DTT) & (NDxI > max_fill_val)] = Min_valid_DTT

    #where T is -999 we should give a no retreival fill value (fill_val_3 = -127)
    DTT[T==-999] = fill_val_3

    return DTT

def get_DTT_White_Test(T, WI, Max_valid_DTT, Min_valid_DTT, fill_val_1,\
                                                        fill_val_2, fill_val_3):

    """
    calculate the distance to threshold metric. This function is valid for
    both near infra-red and for visible reflectance test, as well as for
    spatial variability and cirrus tests.

    [Section 3.3.2.6]

    Arguments:
        T {2D narray} -- Thresholds for observable
        Ref {2D narray} -- observable; choose from whiteness index
        Max_valid_DTT {float} -- from configuration file; upper bound of DTT
        Min_valid_DTT {float} -- from configuration file; lower bound of DTT
        fill_val_1 {integer} -- defined in congifg file; not applied due to surface type
        fill_val_2 {integer} -- defined in congifg file; low quality radiance
        fill_val_3 {integer} -- defined in congifg file; no data

    Returns:
        2D narray -- Distance to threshold calculated for one observable over
                     the whole space.

    """

    max_fill_val = np.max(np.array([fill_val_1, fill_val_2, fill_val_3]))

    DTT = np.copy(WI)
    DTT[WI > max_fill_val] = (100 * (T - WI) / T)[WI > max_fill_val]
    #put upper bound on DTT (fill vals all negative)
    DTT[DTT > Max_valid_DTT]  = Max_valid_DTT
    #put lower bound on DTT where observable is valid (fill vals all negative)
    DTT[(DTT < Min_valid_DTT) & (WI > max_fill_val)] = Min_valid_DTT

    #where T is -999 we should give a no retreival fill value (fill_val_3 = -127)
    DTT[T==-999] = fill_val_3

    return DTT


#apply N tests to activate and activation value from config file****************
#the DTT files with fill values for each observable are ready

def get_cm_confidence(DTT, activation, N, fill_val_2, fill_val_3):
    """calculates final cloud mask based of the DTT, the activation value, and
       N tests needed to activate.

    [Section N/A]

    Arguments:
        DTT {3D narray} -- first 2 axies are granule dimesions, 3rd axies contains
                           DTT for each observable in this order:
                           WI, NDVI, NDSI, VIS Ref, NIR Ref, SVI, Cirrus
        activation {1D narray} -- values for each observable's DTT to exceed to
                                  be called cloudy
        N {integer} -- number of observables which have to activate to be called
                       cloudy.
        fill_val_1 {integer} -- defined in congifg file; not applied due to surface type
        fill_val_2 {integer} -- defined in congifg file; low quality radiance
        fill_val_3 {integer} -- defined in congifg file; no data

    Returns:
        2D narray -- cloud mask; cloudy (0) clear(1) bad data (2) no data (3)

    """
    #create the mask only considering the activation & fill values, not N yet
    #this creates a stack of cloud masks, 7 observables deep, with fill values
    #untouched

    #cloudy_idx contains indicies where each observable independently returned
    #cloudy. The array it refers to is (X,Y,7) for 7 observables calculated over
    #the swath of MAIA
    #essentailly the format is of numpy.where() for 3D array to use later
    # [[    0.     0.     0. ...,  1265.  1265.  1267.]
    #  [   39.    42.    43. ...,   318.   319.   317.]
    #  [    0.     0.     0. ...,     6.     6.     6.]]

    #we must do it like this since each observable has a unique activation value

    #execute above comment blocks
    num_tests  = activation.size
    cloudy_idx = np.where(DTT[:,:,0] >= activation[0])
    #stack the 2D cloudy_idx with a 1D array of zeros denoting 0th element along
    #3rd axis
    zeroth_axis = np.zeros((np.shape(cloudy_idx)[1]))
    cloudy_idx = np.vstack((cloudy_idx,  zeroth_axis))

    #do the same as above in the loop but with the rest of the observables
    #which are stored along the 3rd axis
    for test_num in range(1, num_tests):
        new_cloudy_idx = np.where(DTT[:,:,test_num] >= activation[test_num])
        nth_axis       = np.ones((np.shape(new_cloudy_idx)[1])) * test_num
        new_cloudy_idx = np.vstack((new_cloudy_idx, nth_axis))
        cloudy_idx     = np.concatenate((cloudy_idx, new_cloudy_idx), axis=1)

    cloudy_idx = cloudy_idx.astype(int) #so we can index with this result

    #find indicies where fill values are
    failed_retrieval_idx = np.where(DTT == fill_val_2)
    no_data_idx          = np.where(DTT == fill_val_3)

    DTT_ = np.copy(DTT)
    DTT_[cloudy_idx[0], cloudy_idx[1], cloudy_idx[2]] = 0
    DTT_[failed_retrieval_idx]                        = 2
    DTT_[no_data_idx]                                 = 3
    #can't assign value to 'maybe_cloudy' yet since it would override 'cloudy'
    #we must check the N condition before proceeding on this

    #check N condition to distinguish 'maybe_cloudy' from 'cloudy'
    #count howmany tests returned DTT >= activation value for each pixel
    #To do this, simply add along the third axis each return type for the final
    #cloud mask, 0-3 inclusive
    #check if all tests failed with DTT = -126 <- bad quality data
    #check if all tests failed with DTT = -127 <- no data
    cloudy_test_count      = np.zeros(shape)
    failed_retrieval_count = np.zeros(shape)
    no_data_count          = np.zeros(shape)

    for i in range(num_tests):
        cloudy_idx = np.where(DTT_[:,:,i] == 0)
        cloudy_test_count[cloudy_idx] += 1
        failed_retrieval_idx = np.where(DTT_[:,:,i] == 2)
        failed_retrieval_count[failed_retrieval_idx] += 1

        no_data_idx = np.where(DTT_[:,:,i] == 3)
        no_data_count[no_data_idx] += 1

    #populate final cloud mask; default of one assumes 'maybe cloudy' at all pixels
    final_cm    = np.ones(shape)

    cloudy_idx           = np.where(cloudy_test_count >= N)
    final_cm[cloudy_idx] = 0

    failed_retrieval_idx = np.where(failed_retrieval_count == num_tests)
    final_cm[failed_retrieval_idx] = 2

    no_data_idx = np.where(no_data_count == num_tests)
    final_cm[no_data_idx] = 3

    return final_cm

def MCM_wrapper(test_data_JPL_path, Target_Area_X, threshold_filepath,\
                sfc_ID_filepath, config_filepath):
    """
    simply executes function to get the final cloud mask

    [Section N/A]

    Arguments:
        test_data_JPL_path {string} -- JPL supplied data filepath; example sent to JPL
        Target_Area_X {integer} -- integer corresponding to target area
        threshold_filepath {string} -- ancillary threshold dataset filepath
        sfc_ID_filepath {string} -- ancillary surface ID dataset filepath
        config_filepath {string} -- ancillary configuration file filepath


    Returns:
        Sun_glint_exclusion_angle {float} -- from configuration file in degrees;
                                             scattering angles between 0 and this
                                             are deemed as sunglint for water scenes.
        Max_RDQI {integer} -- from configuration file; denotes minimum usable
                              radiance quality flag
        Max_valid_DTT {float} -- from configuration file; upper bound of DTT
        Min_valid_DTT {float} -- from configuration file; lower bound of DTT
        fill_val_1 {integer} -- defined in congifg file; not applied due to surface type
        fill_val_2 {integer} -- defined in congifg file; low quality radiance
        fill_val_3 {integer} -- defined in congifg file; no data
        Min_num_of_activated_tests {integer} -- same as N. Denotes min number of
                                                tests needed to activate to call
                                                pixel cloudy.
        activation {1D narray} -- values for each observable's DTT to exceed to
                                  be called cloudy
        observable_data {3D narray} -- observables stacked along 3rd axis
        DTT {3D narray} -- first 2 axies are granule dimesions, 3rd axies contains
                           DTT for each observable in this order:
                           WI, NDVI, NDSI, VIS Ref, NIR Ref, SVI, Cirrus
        final_cloud_mask {2D narray} -- cloud mask; cloudy (0) clear(1) bad data
                                                    (2) no data (3)
        BRFs {3D narray} -- reflectances stacked along third axis in this order:
                            bands 4,5,6,9,12,13
        SZA {2D narray} -- solar zenith angle in degrees
        VZA {2D narray} -- viewing (MAIA) zenith angle in degrees
        SAA {2D narray} -- solar azimuth angle in degrees
        VAA {2D narray} -- viewing (MAIA) azimuth angle in degrees
        scene_type_identifier {2D narray} -- scene ID. Values 0-28 inclusive are
                                             land types; values 29, 30, 31 are
                                             water, water with sun glint, snow/ice
                                             respectively.

    """


    start_time = time.time()
    #print('started: ' , 0)

    #get JPL provided data******************************************************
    rad_band_4, rad_band_5, rad_band_6, rad_band_9, rad_band_12, rad_band_13,\
    RDQI_band_4, RDQI_band_5, RDQI_band_6, RDQI_band_9, RDQI_band_12, RDQI_band_13,\
    SZA, VZA, SAA, VAA,\
    d,\
    E_std_0b,\
    snow_ice_mask, land_water_mask,\
    DOY,\
    Target_Area = get_JPL_data(test_data_JPL_path)

    #get UIUC provided data*****************************************************
    T_NDVI,\
    T_NDSI,\
    T_WI,\
    T_VIS_Ref,\
    T_NIR_Ref,\
    T_SVI,\
    T_Cirrus,\
    sfc_ID,\
    Sun_glint_exclusion_angle,\
    Max_RDQI,\
    Max_valid_DTT,\
    Min_valid_DTT,\
    fill_val_1,\
    fill_val_2,\
    fill_val_3,\
    Min_num_of_activated_tests,\
    activation_values = get_UIUC_data(Target_Area_X, threshold_filepath,\
                                      sfc_ID_filepath, config_filepath)

    #now put data through algorithm flow****************************************

    #mark bad radiance**********************************************************
    rad_band_4  = mark_bad_radiance(rad_band_4[:],  RDQI_band_4[:],  Max_RDQI)
    rad_band_5  = mark_bad_radiance(rad_band_5[:],  RDQI_band_5[:],  Max_RDQI)
    rad_band_6  = mark_bad_radiance(rad_band_6[:],  RDQI_band_6[:],  Max_RDQI)
    rad_band_9  = mark_bad_radiance(rad_band_9[:],  RDQI_band_9[:],  Max_RDQI)
    rad_band_12 = mark_bad_radiance(rad_band_12[:], RDQI_band_12[:], Max_RDQI)
    rad_band_13 = mark_bad_radiance(rad_band_13[:], RDQI_band_13[:], Max_RDQI)

    #get R**********************************************************************
    #in order MAIA  bands 6,9,4,5,12,13
    #in order MODIS bands 1,2,3,4,6 ,26
    R_band_4  = get_R(rad_band_4[:],  SZA[:], d, E_std_0b[2])
    R_band_5  = get_R(rad_band_5[:],  SZA[:], d, E_std_0b[3])
    R_band_6  = get_R(rad_band_6[:],  SZA[:], d, E_std_0b[0])
    R_band_9  = get_R(rad_band_9[:],  SZA[:], d, E_std_0b[1])
    R_band_12 = get_R(rad_band_12[:], SZA[:], d, E_std_0b[4])
    R_band_13 = get_R(rad_band_13[:], SZA[:], d, E_std_0b[5])

    BRFs = np.dstack((R_band_4,\
                      R_band_5,\
                      R_band_6,\
                      R_band_9,\
                      R_band_12,\
                      R_band_13))

    #calculate sunglint mask****************************************************
    sun_glint_mask = get_sun_glint_mask(SZA[:], VZA[:], SAA[:], VAA[:],\
                                Sun_glint_exclusion_angle, land_water_mask[:])

    #calculate observables******************************************************
    #0.86, 1.61, 1.88 micrometers -> bands 9, 12, 13
    #RGB channels -> bands 6, 5, 4
    WI      = get_whiteness_index(R_band_6, R_band_5, R_band_4)
    NDVI    = get_NDVI(R_band_6, R_band_9)
    NDSI    = get_NDSI(R_band_5, R_band_12)
    VIS_Ref = get_visible_reflectance(R_band_6)
    NIR_Ref = get_NIR_reflectance(R_band_9)
    Cirrus  = get_cirrus_Ref(R_band_13)
    SVI     = get_spatial_variability_index(R_band_6, shape[0], shape[1])
    
    #SVI_Sfc_ID = get_spatial_variability_index(sfc_ID, shape[0], shape[1])
    #SVI = SVI - SVI_Sfc_ID
    #SVI[SVI<0] = 0
    #Cirrus[Cirrus>2] = -998
    #get observable level parameter*********************************************
    observable_level_parameter = get_observable_level_parameter(SZA[:],\
                VZA[:], SAA[:], VAA[:], Target_Area,land_water_mask[:],\
                    snow_ice_mask[:], sfc_ID[:], DOY, sun_glint_mask[:])

    #return parameters in MCM_wrapper function
    bins =           [SZA[:]            ,\
                      VZA[:]            ,\
                      SAA[:]            ,\
                      VAA[:]            ,\
                      Target_Area       ,\
                      land_water_mask[:],\
                      snow_ice_mask[:]  ,\
                      sfc_ID[:]         ,\
                      DOY               ,\
                      sun_glint_mask[:]   ]

    #get test determination*****************************************************
    #combine observables into one array along third dimesnion
    observables = np.dstack((WI, NDVI, NDSI, VIS_Ref, NIR_Ref, SVI, Cirrus))
    observable_names = ['WI', 'NDVI', 'NDSI', 'VIS_Ref', 'NIR_Ref', 'SVI',\
                        'Cirrus']

    observable_data = np.empty(np.shape(observables))
    T = np.empty(np.shape(observables))
    for i in range(len(observable_names)):
        #threshold_observable_i = threhsold_database[observable_names[i]][:]

        observable_data[:,:,i], T[:,:,i] = \
        get_test_determination(observable_level_parameter,\
        observables[:,:,i],\
        threshold_filepath,\
        observable_names[i],\
        fill_val_1, fill_val_2, fill_val_3)
    #Thresholds
    #l,w, = 20,8
    #import matplotlib.pyplot as plt
    #import matplotlib.cm as cm
    #f2, ax2 = plt.subplots(ncols=4, nrows=2, figsize=(l,w),sharex=True, sharey=True)
    #cmap    = cm.get_cmap('jet')
    ##T[observables == np.nan] = -999
    #im0 = ax2[0,0].imshow(T[:,:,0], cmap=cmap, vmin=T[:,:,0].min(), vmax=T[:,:,0].max())
    #im1 = ax2[0,1].imshow(T[:,:,1], cmap=cmap, vmin=T[:,:,1].min(), vmax=T[:,:,1].max())
    #im2 = ax2[0,2].imshow(T[:,:,2], cmap=cmap, vmin=T[:,:,2].min(), vmax=T[:,:,2].max())
    #im3 = ax2[0,3].imshow(T[:,:,3], cmap=cmap, vmin=T[:,:,3].min(), vmax=T[:,:,3].max())
    #im4 = ax2[1,0].imshow(T[:,:,4], cmap=cmap, vmin=T[:,:,4].min(), vmax=T[:,:,4].max())
    #im5 = ax2[1,1].imshow(T[:,:,5], cmap=cmap, vmin=T[:,:,5].min(), vmax=0.2)
    #im6 = ax2[1,2].imshow(T[:,:,6], cmap=cmap, vmin=T[:,:,6].min(), vmax=T[:,:,6].max())
    #im0.cmap.set_under('k')
    #im1.cmap.set_under('k')
    #im2.cmap.set_under('k')
    #im3.cmap.set_under('k')
    #im4.cmap.set_under('k')
    #im5.cmap.set_under('k')
    #im6.cmap.set_under('k')
    #ax2[0,0].set_title('Thresholds_WI')
    #ax2[0,1].set_title('Thresholds_NDVI')
    #ax2[0,2].set_title('Thresholds_NDSI')
    #ax2[0,3].set_title('Thresholds_VIS_Ref')
    #ax2[1,0].set_title('Thresholds_NIR_Ref')
    #ax2[1,1].set_title('Thresholds_SVI')
    #ax2[1,2].set_title('Thresholds_Cirrus')
    #cbar0 = f2.colorbar(im0, ax=ax2[0,0],fraction=0.046, pad=0.04, ticks = np.arange(0,WI.max()+0.2,0.2))
    #cbar1 = f2.colorbar(im1, ax=ax2[0,1],fraction=0.046, pad=0.04, ticks = np.arange(-1,1.25,0.25))
    #cbar2 = f2.colorbar(im2, ax=ax2[0,2],fraction=0.046, pad=0.04, ticks = np.arange(-1,1.1,0.1))
    #cbar3 = f2.colorbar(im3, ax=ax2[0,3],fraction=0.046, pad=0.04, ticks = np.arange(0,VIS_Ref.max()+0.4,0.2))
    #cbar4 = f2.colorbar(im4, ax=ax2[1,0],fraction=0.046, pad=0.04, ticks = np.arange(0,NIR_Ref.max()+0.1,0.1))
    #cbar5 = f2.colorbar(im5, ax=ax2[1,1],fraction=0.046, pad=0.04, ticks = np.arange(0,SVI.max()+0.1,0.05))
    #cbar6 = f2.colorbar(im6, ax=ax2[1,2],fraction=0.046, pad=0.04, ticks = np.arange(0,1.2,0.2))
    #plt.show()
    #get DTT********************************************************************
    DTT_WI      = get_DTT_White_Test(T[:,:,0], observable_data[:,:,0], \
               Max_valid_DTT, Min_valid_DTT, fill_val_1, fill_val_2, fill_val_3)

    DTT_NDVI    = get_DTT_NDxI_Test(T[:,:,1] , observable_data[:,:,1], \
               Max_valid_DTT, Min_valid_DTT, fill_val_1, fill_val_2, fill_val_3)

    DTT_NDSI    = get_DTT_NDxI_Test(T[:,:,2] , observable_data[:,:,2], \
               Max_valid_DTT, Min_valid_DTT, fill_val_1, fill_val_2, fill_val_3)

    DTT_VIS_Ref = get_DTT_Ref_Test(T[:,:,3]  , observable_data[:,:,3], \
               Max_valid_DTT, Min_valid_DTT, fill_val_1, fill_val_2, fill_val_3)

    DTT_NIR_Ref = get_DTT_Ref_Test(T[:,:,4]  , observable_data[:,:,4], \
               Max_valid_DTT, Min_valid_DTT, fill_val_1, fill_val_2, fill_val_3)

    DTT_SVI     = get_DTT_Ref_Test(T[:,:,5]  , observable_data[:,:,5], \
               Max_valid_DTT, Min_valid_DTT, fill_val_1, fill_val_2, fill_val_3)

    DTT_Cirrus  = get_DTT_Ref_Test(T[:,:,6]  , observable_data[:,:,6], \
               Max_valid_DTT, Min_valid_DTT, fill_val_1, fill_val_2, fill_val_3)


    DTT = np.dstack((DTT_WI     ,\
                     DTT_NDVI   ,\
                     DTT_NDSI   ,\
                     DTT_VIS_Ref,\
                     DTT_NIR_Ref,\
                     DTT_SVI    ,\
                     DTT_Cirrus))

    #in order the activation values are
    #WI, NDVI, NDSI, VIS Ref, NIR Ref, SVI, Cirrus
    #I reformat the values as such since the code handles each observable
    #independently, even if two observables belong to the same test
    activation_values = np.array([activation_values[0],\
                                  activation_values[1],\
                                  activation_values[1],\
                                  activation_values[2],\
                                  activation_values[2],\
                                  activation_values[3],\
                                  activation_values[4]])

    final_cloud_mask = get_cm_confidence(DTT, activation_values,\
                             Min_num_of_activated_tests, fill_val_2, fill_val_3)

    #print('finished: ' , time.time() - start_time)

    scene_type_identifier = make_sceneID(observable_level_parameter,observable_level_parameter[:,:,4],\
                     observable_level_parameter[:,:,8], observable_level_parameter[:,:,5])

    return Sun_glint_exclusion_angle,\
           Max_RDQI,\
           Max_valid_DTT,\
           Min_valid_DTT,\
           fill_val_1,\
           fill_val_2,\
           fill_val_3,\
           Min_num_of_activated_tests,\
           activation_values,\
           observable_data,\
           DTT, final_cloud_mask,\
           BRFs,\
           SZA, VZA, VAA,SAA,\
           scene_type_identifier


#badda bing badda boom... cloud mask********************************************

if __name__ == '__main__':
    pass
