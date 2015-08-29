import colonyzer2 as c2
import json
import argparse
import shutil
import string
import os
import time
import numpy
import itertools
from matplotlib.backends.backend_pdf import PdfPages


def checkImages(fdir,fdict=None,barcRange=(0,-24),verbose=False):
    '''Discover barcodes in current working directory (or in fdir or in those specified in fdict) for which analysis has not started.'''
    if fdict!=None:
        with open(fdict, 'rb') as fp:
            barcdict = json.load(fp)
            # Drop any barcodes that are currently being analysed/already analysed
            barcdict={x:barcdict[x] for x in barcdict.keys() if not c2.checkAnalysisStarted(barcdict[x][-1])}
    else:
        # Find image files which have yet to be analysed
        # Lydall lab file naming convention (barcRange)
        # First 15 characters in filename identify unique plates
        # Remaining charaters can be used to store date, time etc.
        barcdict=c2.getBarcodes(fdir,barcRange,verbose=verbose)
    return(barcdict)

def parseArgs(inp=''):
    '''Define console script behaviour, hints and documentation for setting off Colonyzer analysis.'''
    parser=argparse.ArgumentParser(description="Analyse timeseries of QFA images: locate cultures on plate, segment image into agar and cells, apply lighting correction, write report including cell density estimates for each location in each image.  If you need to specify initial guesses for colony locations, you must provide a Colonyzer.txt file (as generated by ColonyzerParametryzer) describing initial guess for culture array in the directory containing the images to be analysed.")

    parser.add_argument("-c","--lc", help="Enable lighting correction?", action="store_true")
    parser.add_argument("-t","--threshplots", help="Plot pixel intensity distributions and segmentation thresholds?", action="store_true")
    parser.add_argument("-i","--initpos", help="Use intial guess for culture positions from Colonyzer.txt file?", action="store_true")
    
    parser.add_argument("-d","--dir", type=str, help="Directory in which to search for image files that have not been analysed (current directory by default).",default=".")
    parser.add_argument("-l","--logsdir", type=str, help="Directory in which to search for JSON files listing images for analyis (e.g. LOGS3, root of HTS filestore).  Only used when intending to specify images for analysis in .json file (see -u).",default=".")
    parser.add_argument("-f","--fixthresh", type=float, help="Image segmentation threshold value (default is automatic thresholding).")
    parser.add_argument("-u","--usedict", type=str, help="Load .json file specifying images to analyse.  If argument has a .json extension, treat as filename.  Otherwise assume argument is a HTS-style screen ID and return path to appropriate .json file from directory structure.  See C2Find.py in HTSauto package.")
    parser.add_argument("-o","--fmt", type=str, nargs='+', help="Specify rectangular grid format, either using integer shorthand (e.g. -o 96, -o 384, -o 768 -o 1536) or explicitly specify number of rows followed by number of columns (e.g.: -o 24 16 or -o 24x16)", default=['384'])

    if inp=="":
        args = parser.parse_args()
    else:
        args = parser.parse_args(inp.split())
    return(args)

def buildVars(inp='',verbose=False):
    '''Read user input, set up flags for analysis, report on options chosen and find files to be analysed.'''
    inp=parseArgs(inp)
    
    if inp.dir==None:
        fdir=os.getcwd()
    else:
        fdir=os.path.realpath(inp.dir)

    if inp.fixthresh!=None:
        fixedThresh=inp.fixthresh
    else:
        fixedThresh=-99

    if len(inp.fmt)>2:
        print("Woah!  Too many dimensions specified for rectangular grid format!")
        nrow,ncol=(0,0)
    elif len(inp.fmt)==1:
        nrow,ncol=c2.parsePlateFormat(inp.fmt[0])
    else:
        nrow,ncol=[int(x) for x in inp.fmt]
    
    if inp.usedict is None:
        fdict=None    
    elif inp.usedict[-5:] in [".json",".JSON"]:
        fdict=os.path.realpath(inp.usedict)
    else:
        fdict=locateJSON(inp.usedict,os.path.realpath(inp.logsdir),verbose)
    if fdict is not None and not os.path.exists(fdict): print("WARNING! "+fdict+" does not exist...")

    if verbose:
        if inp.lc:
            print("Lighting correction turned on.")
        else:
            print("Lighting correction turned off.")
        if inp.threshplots:
            print("Pixel intensity distribution plotting turned on.")
        else:
            print("Pixel intensity distribution plotting turned off.")
        if inp.initpos:
            print("Using user-specified initial guess for colony locations.  NOTE: Colonyzer.txt file must be located in directory with images to be analysed.  See Parametryzer for more information.")
        else:
            print("Searching for colony locations automatically.")
        if fixedThresh==-99:
            print("Image segmentation by automatic thresholding.")
        else:
            print("Images will be segmented using fixed threshold: "+str(fixedThresh)+".")
        if fdict is not None and os.path.exists(fdict):
            print("Preparing to load barcodes from "+fdict+".")
    res={'lc':inp.lc,'fixedThresh':fixedThresh,'threshplots':inp.threshplots,'initpos':inp.initpos,'fdict':fdict,'fdir':fdir,'nrow':nrow,'ncol':ncol}
    print(res)
    return(res)

def locateJSON(scrID,dirHTS='.',verbose=False):
    exptType=scrID[0:-4]
    fdict=os.path.join(dirHTS,exptType+"_EXPERIMENTS",scrID,"AUXILIARY",scrID+"_C2.json")
    return(fdict)

def prepareTimecourse(barcdict,verbose=False):
    '''In timecourse mode, prepares "next" batch of images for analysis from dictionary of image names (unique image barcodes are dictionary keys).'''
    #BARCs=barcdict.keys()
    #BARCs.sort()
    BARCs=sorted(barcdict)
    BARCODE=BARCs[0]
    imdir=os.path.dirname(barcdict[BARCODE][0])
    InsData=c2.readInstructions(imdir)
    IMs=barcdict[BARCODE]
    LATESTIMAGE=IMs[0]
    EARLIESTIMAGE=IMs[-1]
    imRoot=EARLIESTIMAGE.split(".")[0]
    if verbose:
        print("Analysing images labelled with the barcode "+BARCODE+" in "+imdir)
        print("Earliest image: "+EARLIESTIMAGE)
        print("Latest image: "+LATESTIMAGE)
    return((BARCODE,imdir,InsData,LATESTIMAGE,EARLIESTIMAGE,imRoot))

def loadLocationGuesses(IMAGE,InsData):
    '''Set up initial guesses for location of (centres of) spots on image by parsing data from Colonyzer.txt'''
    # If we have ColonyzerParametryzer output for this filename, use it for initial culture location estimates
    if os.path.basename(IMAGE) in InsData:
        (candx,candy,dx,dy)=c2.SetUp(InsData[os.path.basename(IMAGE)])
    # If there are multiple calibrations available, choose the best one based on date of image capture
    elif any(isinstance(el, list) for el in InsData['default']):
        imname=os.path.basename(IMAGE).split(".")[0]
        imdate=imname[-19:-9]
        (candx,candy,dx,dy)=c2.SetUp(InsData['default'],imdate)
    else:
        (candx,candy,dx,dy)=c2.SetUp(InsData['default'])
    return((candx,candy,dx,dy))

def cutEdgesFromMask(mask,locations):
    '''Mask for identifying culture areas (edge detection). Set all pixels outside culture grid to background, to aid binary filling later.'''
    mask[0:min(locations.y-dy/2),:]=False
    mask[max(locations.y+dy/2):mask.shape[0],:]=False
    mask[:,0:min(locations.x-dx/2)]=False
    mask[:,max(locations.x+dx/2):mask.shape[1]]=False
    return(mask)

def edgeFill(arr,locations,cutoff=0.8):
    edgeN=getEdges(arr,cutoff=0.8)
    dilN=ndimage.morphology.binary_dilation(edgeN,iterations=2)
    erodeN=ndimage.morphology.binary_erosion(dilN,iterations=1)
    dil2N=ndimage.morphology.binary_dilation(dilN,iterations=3)
    
    fillN=ndimage.morphology.binary_fill_holes(cutEdgesFromMask(dil2N,locations))
    maskN=ndimage.morphology.binary_erosion(fillN,iterations=7)
    return(maskN)


def main(inp="",verbose=False):
    print("Colonyzer "+c2.__version__)

    cutFromFirst=False
    cythonFill=False
    updateLocations=False

    var=buildVars(verbose=verbose,inp=inp)
    correction,fixedThresh,threshplots,initpos,fdict,fdir,nrow,ncol=(var["lc"],var["fixedThresh"],var["threshplots"],var["initpos"],var["fdict"],var["fdir"],var["nrow"],var["ncol"])
    barcdict=checkImages(fdir,fdict,verbose=verbose)
    rept=c2.setupDirectories(barcdict,verbose=verbose)

    start=time.time()

    while len(barcdict)>0:
        BARCODE,imdir,InsData,LATESTIMAGE,EARLIESTIMAGE,imRoot=prepareTimecourse(barcdict,verbose=verbose)  
       
        # Create empty file to indicate that barcode is currently being analysed, to allow parallel analysis (lock files)
        tmp=open(os.path.join(os.path.dirname(EARLIESTIMAGE),"Output_Data",os.path.basename(EARLIESTIMAGE).split(".")[0]+".out"),"w").close()

        # Get latest image for thresholding and detecting culture locations
        imN,arrN=c2.openImage(LATESTIMAGE)
        # Get earliest image for lighting gradient correction
        im0,arr0=c2.openImage(EARLIESTIMAGE)

        if initpos:
            # Load initial guesses from Colonyzer.txt file
            (candx,candy,dx,dy)=loadLocationGuesses(LATESTIMAGE,InsData)
        else:
            # Automatically generate guesses for gridded array locations
            (candx,candy,dx,dy)=c2.estimateLocations(arrN,ncol,nrow,showPlt=True)

        # Update guesses and initialise locations data frame
        locationsN=c2.locateCultures([int(round(cx-dx/2.0)) for cx in candx],[int(round(cy-dy/2.0)) for cy in candy],dx,dy,arrN,update=updateLocations,mkPlots=False)

        if cutFromFirst:
            mask=edgeFill(arr0,locationsN,0.8)
            startFill=time.time()
            if cythonFill:
                pseudoempty=maskAndFillCython(arr0,maskN,0.005)
                print("Inpainting using Cython & NumPy: "+str(time.time()-startFill)+" s")
            else:
                pseudoempty=maskAndFill(arr0,mask,0.005)
                print("Inpainting using NumPy: "+str(time.time()-start)+" s")
        else:
            pseudoempty=arr0
            
        # Smooth (pseudo-)empty image 
        (correction_map,average_back)=c2.makeCorrectionMap(pseudoempty,locationsN,verbose=verbose)

        # Correct spatial gradient in final image
        corrected_arrN=arrN*correction_map

        # Trim outer part of image to remove plate walls
        trimmed_arrN=arrN[max(0,int(round(min(locationsN.y)-dy/2.0))):min(arrN.shape[0],int(round((max(locationsN.y)+dy/2.0)))),max(0,int(round(min(locationsN.x)-dx/2.0))):min(arrN.shape[1],int(round((max(locationsN.x)+dx/2.0))))]
        
        if fixedThresh>=0:
            thresh=fixedThresh
        else:
            if threshplots:
                pdf=PdfPages(BARCODE+'_HistogramReport.pdf')
                (thresh,bindat)=c2.automaticThreshold(trimmed_arrN,BARCODE,pdf)
                c2.plotModel(bindat,label=BARCODE,pdf=pdf)
                pdf.close()
            else:
                (thresh,bindat)=c2.automaticThreshold(trimmed_arrN)

        # Mask for identifying culture areas
        maskN=numpy.ones(arrN.shape,dtype=numpy.bool)
        maskN[arrN<thresh]=False

        for FILENAME in barcdict[BARCODE]:
            im,arr=c2.openImage(FILENAME)
            if correction:
                arr=arr*correction_map
            
            # Correct for lighting differences between plates
            arrsm=arr[max(0,int(round(min(locationsN.y)-dy/2.0))):min(arrN.shape[0],int(round((max(locationsN.y)+dy/2.0)))),max(0,int(round(min(locationsN.x)-dx/2.0))):min(arrN.shape[1],int(round((max(locationsN.x)+dx/2.0))))]
            masksm=maskN[max(0,int(round(min(locationsN.y)-dy/2.0))):min(arrN.shape[0],int(round((max(locationsN.y)+dy/2.0)))),max(0,int(round(min(locationsN.x)-dx/2.0))):min(arrN.shape[1],int(round((max(locationsN.x)+dx/2.0))))]
            meanPx=numpy.mean(arrsm[numpy.logical_not(masksm)])

            #arr=arr+(average_back-meanPx)
            #threshadj=thresh+(average_back-meanPx)
            threshadj=thresh

            mask=numpy.ones(arr.shape,dtype=numpy.bool)
            mask[arrN<threshadj]=False

            # Measure culture phenotypes
            locations=c2.measureSizeAndColour(locationsN,arr,im,mask,average_back,BARCODE,FILENAME[0:-4])

            # Write results to file
            locations.to_csv(os.path.join(os.path.dirname(FILENAME),"Output_Data",os.path.basename(FILENAME).split(".")[0]+".out"),"\t",index=False,engine='python')
            dataf=c2.saveColonyzer(os.path.join(os.path.dirname(FILENAME),"Output_Data",os.path.basename(FILENAME).split(".")[0]+".dat"),locations,threshadj,dx,dy)

            # Visual check of culture locations
            imthresh=c2.threshPreview(arr,threshadj,locations)
            imthresh.save(os.path.join(os.path.dirname(FILENAME),"Output_Images",os.path.basename(FILENAME).split(".")[0]+".png"))

        # Get ready for next image
        print("Finished: "+FILENAME+" "+str(time.time()-start)+" s")

        barcdict={x:barcdict[x] for x in barcdict.keys() if not c2.checkAnalysisStarted(barcdict[x][-1])}

    print("No more barcodes to analyse... I'm done.")

if __name__ == '__main__':
    main(verbose=True,inp="-d ../Auxiliary/Data -c -t -o 384")
