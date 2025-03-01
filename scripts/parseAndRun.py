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
from PIL import Image,ImageDraw

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
    parser.add_argument("-m","--diffims", help="If lighting correction switched on, attempt to correct for lighting differences between images in timecourse (can induce slight negative cell density estimates).", action="store_true")
    parser.add_argument("-p","--plots", help="Plot pixel intensity distributions, segmentation thresholds and spot location traces?", action="store_true")
    parser.add_argument("-i","--initpos", help="Use intial guess for culture positions from Colonyzer.txt file?", action="store_true")
    parser.add_argument("-x","--cut", help="Cut culture signal from first image to make pseudo-empty plate?", action="store_true")
    parser.add_argument("-q","--quiet", help="Suppress messages printed to screen during analysis?", action="store_true")
    
    parser.add_argument("-d","--dir", type=str, help="Directory in which to search for image files that have not been analysed (current directory by default).",default=".")
    parser.add_argument("-l","--logsdir", type=str, help="Directory in which to search for JSON files listing images for analyis (e.g. LOGS3, root of HTS filestore).  Only used when intending to specify images for analysis in .json file (see -u).",default=".")
    parser.add_argument("-f","--fixthresh", type=float, help="Image segmentation threshold value (default is automatic thresholding).")
    parser.add_argument("-u","--usedict", type=str, help="Load .json file specifying images to analyse.  If argument has a .json extension, treat as filename.  Otherwise assume argument is a HTS-style screen ID and return path to appropriate .json file from directory structure.  See C2Find.py in HTSauto package.")
    parser.add_argument("-o","--fmt", type=str, nargs='+', help="Specify rectangular grid format, either using integer shorthand (e.g. -o 96, -o 384, -o 768 -o 1536) or explicitly specify number of rows followed by number of columns (e.g.: -o 24 16 or -o 24x16)", default=['384'])
    #parser.add_argument("-","--fmt", type=str, nargs='+', help="Specify rectangular grid format, either using integer shorthand (e.g. -o 96, -o 384, -o 768 -o 1536) or explicitly specify number of rows followed by number of columns (e.g.: -o 24 16 or -o 24x16)", default=['384'])
    

    if inp=="":
        args = parser.parse_args()
    else:
        args = parser.parse_args(inp.split())
    return(args)

def buildVars(inp=''):
    '''Read user input, set up flags for analysis, report on options chosen and find files to be analysed.'''
    inp=parseArgs(inp)

    if inp.quiet:
        verbose=False
    else:
        verbose=True
    
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
        diffIms=False
        if inp.lc:
            if inp.diffims:
                print("Correcting for lighting differences between subsequent images of same plate.")
                diffIms=True
            else:
                print("Any lighting differences between plates will be ignored.")
        if inp.plots:
            print("Reports on spot location and thresholding will appear in Output_Reports directory.")
        else:
            print("No reports on spot location or thresholding will be generated.")
        if inp.initpos:
            print("Using user-specified initial guess for colony locations.  NOTE: Colonyzer.txt file must be located in directory with images to be analysed.  See Parametryzer for more information.")
        else:
            print("Searching for colony locations automatically.")
        cut=False
        if inp.lc:
            if inp.cut:
                print("Cutting cell signal from first image to create pseudo-empty plate (for lighting correction).")
                cut=True
            else:
                print("Using first plate (without segmenting) as best estimate of pseudo-empty plate (for lighting correction).")
        if fixedThresh==-99:
            print("Image segmentation by automatic thresholding.")
        else:
            print("Images will be segmented using fixed threshold: "+str(fixedThresh)+".")
        if fdict is not None and os.path.exists(fdict):
            print("Preparing to load barcodes from "+fdict+".")
    res={'lc':inp.lc,'fixedThresh':fixedThresh,'plots':inp.plots,'initpos':inp.initpos,'fdict':fdict,'fdir':fdir,'nrow':nrow,'ncol':ncol,'cut':cut,'verbose':verbose,'diffims':diffIms}
    return(res)

def locateJSON(scrID,dirHTS='.',verbose=False):
    exptType=scrID[0:-4]
    fdict=os.path.join(dirHTS,exptType+"_EXPERIMENTS",scrID,"AUXILIARY",scrID+"_C2.json")
    return(fdict)

def prepareTimecourse(barcdict,verbose=False):
    '''In timecourse mode, prepares "next" batch of images for analysis from dictionary of image names (unique image barcodes are dictionary keys).'''
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

def main(inp=""):
    print("Colonyzer "+c2.__version__)

    cythonFill=False

    var=buildVars(inp=inp)
    correction,fixedThresh,plots,initpos,fdict,fdir,nrow,ncol,cut,verbose,diffIms=(var["lc"],var["fixedThresh"],var["plots"],var["initpos"],var["fdict"],var["fdir"],var["nrow"],var["ncol"],var["cut"],var["verbose"],var["diffims"])
    barcdict=checkImages(fdir,fdict,verbose=verbose)
    rept=c2.setupDirectories(barcdict,verbose=verbose)

    start=time.time()

    while len(barcdict)>0:

        BARCODE,imdir,InsData,LATESTIMAGE,EARLIESTIMAGE,imRoot=prepareTimecourse(barcdict,verbose=verbose)  

        if plots:
            pdf=PdfPages(os.path.join(os.path.dirname(EARLIESTIMAGE),"Output_Reports",os.path.basename(EARLIESTIMAGE).split(".")[0]+".pdf"))
        else:
            pdf=None
        
        # Create empty file to indicate that barcode is currently being analysed, to allow parallel analysis (lock files)
        tmp=open(os.path.join(os.path.dirname(EARLIESTIMAGE),"Output_Data",os.path.basename(EARLIESTIMAGE).split(".")[0]+".out"),"w").close()

        # Get latest image for thresholding and detecting culture locations
        imN,arrN=c2.openImage(LATESTIMAGE)
        # Get earliest image for lighting gradient correction
        if(LATESTIMAGE==EARLIESTIMAGE):
            im0,arr0=imN,arrN
        else:
            im0,arr0=c2.openImage(EARLIESTIMAGE)

        if initpos:
            # Load initial guesses from Colonyzer.txt file
            (candx,candy,dx,dy)=loadLocationGuesses(LATESTIMAGE,InsData)
            corner=[0,0]; com=[0,0]; guess=[0,0]
        else:
            # Automatically generate guesses for gridded array locations
            (candx,candy,dx,dy,corner,com,guess)=c2.estimateLocations(arrN,ncol,nrow,showPlt=plots,pdf=pdf,glob=False,verbose=verbose)

        # Update guesses and initialise locations data frame
        locationsN=c2.locateCultures([int(round(cx-dx/2.0)) for cx in candx],[int(round(cy-dy/2.0)) for cy in candy],dx,dy,arrN,ncol,nrow,update=True)

        if correction:
            if cut:
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
        else:
            average_back=numpy.mean(arr0[numpy.min(locationsN.y):numpy.max(locationsN.y),numpy.min(locationsN.x):numpy.max(locationsN.x)])
            corrected_arrN=arrN

        # Trim outer part of image to remove plate walls
        trimmed_arrN=corrected_arrN[max(0,int(round(min(locationsN.y)-dy/2.0))):min(arrN.shape[0],int(round((max(locationsN.y)+dy/2.0)))),max(0,int(round(min(locationsN.x)-dx/2.0))):min(arrN.shape[1],int(round((max(locationsN.x)+dx/2.0))))]
        
        if fixedThresh>=0:
            thresh=fixedThresh
        else:
            (thresh,bindat)=c2.automaticThreshold(trimmed_arrN,BARCODE,pdf=pdf)
            if plots:
                c2.plotModel(bindat,label=BARCODE,pdf=pdf)

        # Mask for identifying culture areas
        maskN=numpy.ones(arrN.shape,dtype=numpy.bool)
        maskN[corrected_arrN<thresh]=False

        for FILENAME in barcdict[BARCODE]:

            startim=time.time()
            
            im,arr=c2.openImage(FILENAME)
            if correction:
                arr=arr*correction_map

            if diffIms:
                # Correct for lighting differences between plates
                arrsm=arr[max(0,int(round(min(locationsN.y)-dy/2.0))):min(arrN.shape[0],int(round((max(locationsN.y)+dy/2.0)))),max(0,int(round(min(locationsN.x)-dx/2.0))):min(arrN.shape[1],int(round((max(locationsN.x)+dx/2.0))))]
                masksm=maskN[max(0,int(round(min(locationsN.y)-dy/2.0))):min(arrN.shape[0],int(round((max(locationsN.y)+dy/2.0)))),max(0,int(round(min(locationsN.x)-dx/2.0))):min(arrN.shape[1],int(round((max(locationsN.x)+dx/2.0))))]
                meanPx=numpy.mean(arrsm[numpy.logical_not(masksm)])

                arr=arr+(average_back-meanPx)
                threshadj=thresh+(average_back-meanPx)
            else:
                threshadj=thresh

            mask=numpy.ones(arr.shape,dtype=numpy.bool)
            mask[corrected_arrN<threshadj]=False

            # Measure culture phenotypes
            locations=c2.measureSizeAndColour(locationsN,arr,im,mask,average_back,BARCODE,FILENAME[0:-4])

            # Write results to file
            locations.to_csv(os.path.join(os.path.dirname(FILENAME),"Output_Data",os.path.basename(FILENAME).split(".")[0]+".out"),"\t",index=False,engine='python')
            dataf=c2.saveColonyzer(os.path.join(os.path.dirname(FILENAME),"Output_Data",os.path.basename(FILENAME).split(".")[0]+".dat"),locations,threshadj,dx,dy)

            # Visual check of culture locations
            imthresh=c2.threshPreview(arr,threshadj,locations)
            r=5
            draw=ImageDraw.Draw(imthresh)
            draw.ellipse((com[1]-r,com[0]-r,com[1]+r,com[0]+r),fill=(255,0,0))
            draw.ellipse((corner[1]-r,corner[0]-r,corner[1]+r,corner[0]+r),fill=(255,0,0))
            draw.ellipse((guess[1]-r,guess[0]-r,guess[1]+r,guess[0]+r),fill=(255,0,0))
            draw.ellipse((candx[0]-r,candy[0]-r,candx[0]+r,candy[0]+r),fill=(255,0,0))
            imthresh.save(os.path.join(os.path.dirname(FILENAME),"Output_Images",os.path.basename(FILENAME).split(".")[0]+".png"))

            # Get ready for next image
            if verbose: print("Finished {0} in {1:.2f}s".format(os.path.basename(FILENAME),time.time()-startim))

        # Get ready for next image
        if verbose: print("Finished {0} in {1:.2f}s".format(os.path.basename(BARCODE),time.time()-start))

        barcdict={x:barcdict[x] for x in barcdict.keys() if not c2.checkAnalysisStarted(barcdict[x][-1])}
        if plots:
            pdf.close()

    print("No more barcodes to analyse... I'm done.")

if __name__ == '__main__':
    main()
