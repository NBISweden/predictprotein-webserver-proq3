#!/usr/bin/env python
# Description: run job

# Derived from topcons2_workflow_run_job.py
# how to create md5
# import hashlib
# md5_key = hashlib.md5(string).hexdigest()
# subfolder = md5_key[:2]

# 

import os
import sys
import subprocess
import time
import myfunc
import glob
import hashlib
import shutil
from datetime import datetime
progname =  os.path.basename(sys.argv[0])
wspace = ''.join([" "]*len(progname))
rundir = os.path.dirname(os.path.realpath(__file__))
suq_basedir = "/tmp"
if os.path.exists("/scratch"):
    suq_basedir = "/scratch"
elif os.path.exists("/tmp"):
    suq_basedir = "/tmp"

runscript = "%s/%s"%(rundir, "soft/proq3/run_proq3.sh")
pdb2aa_script = "%s/%s"%(rundir, "soft/proq3/bin/aa321CA.pl")

basedir = os.path.realpath("%s/.."%(rundir)) # path of the application, i.e. pred/
path_md5cache = "%s/static/md5"%(basedir)
path_profile_cache = "%s/static/result/profilecache/"%(basedir)

contact_email = "nanjiang.shu@scilifelab.se"
vip_user_list = [
        "nanjiang.shu@scilifelab.se"
        ]

# note that here the url should be without http://

usage_short="""
Usage: %s dumped-model-file [-fasta seqfile]
       %s [-r yes|no] [-k yes|no] [-t INT]
       %s -jobid JOBID -outpath DIR -tmpdir DIR
       %s -email EMAIL -baseurl BASE_WWW_URL
       %s [-force]
"""%(progname, wspace, wspace, wspace, wspace)

usage_ext="""\
Description:
    run job

OPTIONS:
  -r    yes|no  Whether do repacking
  -k    yes|no  Whether keep SVM results and repacked models
  -t       INT  Set the target length
  -force        Do not use cahced result
  -h, --help    Print this help message and exit

Created 2016-02-02, updated 2016-02-02, Nanjiang Shu
"""
usage_exp="""
Examples:
    %s /data3/tmp/tmp_dkgSD/query.pdb -outpath /data3/result/rst_mXLDGD -tmpdir /data3/tmp/tmp_dkgSD
"""%(progname)

def PrintHelp(fpout=sys.stdout):#{{{
    print >> fpout, usage_short
    print >> fpout, usage_ext
    print >> fpout, usage_exp#}}}

def ReadProQ3GlobalScore(infile):#{{{
    globalscore = {}
    try:
        fpin = open(infile, "r")
        lines = fpin.read().split("\n")
        fpin.close()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line[0] == "P":
                keys = line.split()
            elif line[0].isdigit():
                values = line.split()
                try:
                    values = [float(x) for x in values]
                except:
                    values = []
        if len(keys) == len(values):
            for i in xrange(len(keys)):
                globalscore[keys[i]] = values[i]
    except IOError:
        pass
    return globalscore
#}}}
def WriteTextResultFile(outfile, outpath_result, modelFileList, runtime_in_sec, statfile=""):#{{{
    try:
        fpout = open(outfile, "w")

        fpstat = None
        numTMPro = 0

        if statfile != "":
            fpstat = open(statfile, "w")
        numModel = len(modelFileList)

        date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print >> fpout, "##############################################################################"
        print >> fpout, "# ProQ3 result file"
        print >> fpout, "# Generated from %s at %s"%(g_params['base_www_url'], date)
        print >> fpout, "# Options for Proq3: %s"%(g_params['proq3opt'])
        print >> fpout, "# Total request time: %.1f seconds."%(runtime_in_sec)
        print >> fpout, "# Number of finished models: %d"%(numModel)
        print >> fpout, "##############################################################################"
        print >> fpout
        print >> fpout, "# Global scores"
        print >> fpout, "# %10s %12s %12s %12s %12s"%("Model", "ProQ2","ProQ_Lowres","ProQ_Highres","ProQ3")

        cnt = 0
        for i  in xrange(numModel):
            modelfile = modelFileList[i]
            globalscorefile = "%s.proq3.global"%(modelfile)
            globalscore = ReadProQ3GlobalScore(globalscorefile)
            try:
                if globalscore:
                    print >> fpout, "%2s %10s %12f %12f %12f %12f"%("", "model_%d"%(i),
                            globalscore['ProQ2'], globalscore['ProQ_Lowres'],
                            globalscore['ProQ_Highres'], globalscore['ProQ3'])
                else:
                    print >> fpout, "%2s %10s"%("", "model_%d"%(i))
            except:
                pass

        print >> fpout, "\n# Local scores"
        for i  in xrange(numModel):
            modelfile = modelFileList[i]
            localscorefile = "%s.proq3.local"%(modelfile)
            print >> fpout, "\n# Model %d"%(i)
            content = myfunc.ReadFile(localscorefile)
            print >> fpout, content

    except IOError:
        print "Failed to write to file %s"%(outfile)
#}}}
def CreateProfile(seqfile, outpath_profile, outpath_result, tmp_outpath_result, timefile, runjob_errfile):#{{{
    (seqid, seqanno, seq) = myfunc.ReadSingleFasta(seqfile)
    subfoldername_profile = os.path.basename(outpath_profile)
    tmp_outpath_profile = "%s/%s"%(tmp_outpath_result, subfoldername_profile)
    isSkip = False
    if not g_params['isForceRun']:
        md5_key = hashlib.md5(seq).hexdigest()
        subfoldername = md5_key[:2]
        md5_link = "%s/%s/%s"%(path_md5cache, subfoldername, md5_key)
        if os.path.exists(md5_link):
            # create a symlink to the cache
            rela_path = os.path.relpath(md5_link, outpath_result) #relative path
            os.chdir(outpath_result)
            os.symlink(rela_path, subfoldername_profile)
            isSkip = True
    if not isSkip:
        # build profiles
        if not os.path.exists(tmp_outpath_profile):
            try:
                os.makedirs(tmp_outpath_profile)
            except OSError:
                msg = "Failed to create folder %s"%(tmp_outpath_profile)
                myfunc.WriteFile(msg+"\n", runjob_errfile, "a")
                return 1
        cmd = [runscript, "-fasta", seqfile,  "-outpath", tmp_outpath_profile, "-only-build-profile"]
        g_params['runjob_log'].append(" ".join(cmd))
        begin_time = time.time()
        try:
            rmsg = subprocess.check_output(cmd)
            g_params['runjob_log'].append("profile_building:\n"+rmsg+"\n")
        except subprocess.CalledProcessError, e:
            g_params['runjob_err'].append(str(e)+"\n")
            g_params['runjob_err'].append(rmsg + "\n")
            pass
        end_time = time.time()
        runtime_in_sec = end_time - begin_time
        msg = "%s\t%f\n"%(subfoldername_profile, runtime_in_sec)
        myfunc.WriteFile(msg, timefile, "a")

        if os.path.exists(tmp_outpath_profile):
            md5_key = hashlib.md5(seq).hexdigest()
            md5_subfoldername = md5_key[:2]
            subfolder_profile_cache = "%s/%s"%(path_profile_cache, md5_subfoldername)
            outpath_profile_cache = "%s/%s"%(subfolder_profile_cache, md5_key)
            if os.path.exists(outpath_profile_cache):
                shutil.rmtree(outpath_profile_cache)
            if not os.path.exists(subfolder_profile_cache):
                os.makedirs(subfolder_profile_cache)
            cmd = ["mv","-f", tmp_outpath_profile, outpath_profile_cache]
            isCmdSuccess = False
            try:
                subprocess.check_output(cmd)
                isCmdSuccess = True
            except subprocess.CalledProcessError, e:
                msg =  "Failed to run get profile for the target sequence %s"%(seq)
                g_params['runjob_err'].append(msg)
                g_params['runjob_err'].append(str(e)+"\n")
                pass

            if isCmdSuccess and g_params['base_www_url'].find("bioinfo") != -1:
                # create soft link for profile and for md5
                # first create a soft link for outpath_profile to outpath_profile_cache
                rela_path = os.path.relpath(outpath_profile_cache, outpath_result) #relative path
                try:
                    os.chdir(outpath_result)
                    os.symlink(rela_path,  subfoldername_profile)
                except:
                    pass

                # then create a soft link for md5 to outpath_proifle_cache
                md5_subfolder = "%s/%s"%(path_md5cache, md5_subfoldername)
                md5_link = "%s/%s/%s"%(path_md5cache, md5_subfoldername, md5_key)
                if os.path.exists(md5_link):
                    try:
                        os.unlink(md5_link)
                    except:
                        pass
                if not os.path.exists(md5_subfolder):
                    try:
                        os.makedirs(md5_subfolder)
                    except:
                        pass

                rela_path = os.path.relpath(outpath_profile_cache, md5_subfolder) #relative path
                try:
                    os.chdir(md5_subfolder)
                    os.symlink(rela_path,  md5_key)
                except:
                    pass
#}}}
def ScoreModel(model_file, outpath_this_model, profilename, outpath_result, #{{{
        tmp_outpath_result, timefile, runjob_errfile, isRepack, isKeepFiles,
        targetlength): 
    subfoldername_this_model = os.path.basename(outpath_this_model)
    modelidx = int(subfoldername_this_model.split("model_")[1])
    tmp_outpath_this_model = "%s/%s"%(tmp_outpath_result, subfoldername_this_model)
    cmd = [runscript, "-profile", profilename,  "-outpath",
            tmp_outpath_this_model, model_file, "-r", isRepack, "-k",
            isKeepFiles]
    if targetlength != None:
        cmd += ["-t", str(targetlength)]
    g_params['runjob_log'].append(" ".join(cmd))
    begin_time = time.time()
    try:
        rmsg = subprocess.check_output(cmd)
        g_params['runjob_log'].append("model scoring:\n"+rmsg+"\n")
    except subprocess.CalledProcessError, e:
        g_params['runjob_err'].append(str(e)+"\n")
        g_params['runjob_err'].append(rmsg + "\n")
        pass
    end_time = time.time()
    runtime_in_sec = end_time - begin_time
    msg = "%s\t%f\n"%(subfoldername_this_model, runtime_in_sec)
    myfunc.WriteFile(msg, timefile, "a")
    if os.path.exists(tmp_outpath_this_model):
        cmd = ["mv","-f", tmp_outpath_this_model, outpath_this_model]
        isCmdSuccess = False
        try:
            subprocess.check_output(cmd)
            isCmdSuccess = True
        except subprocess.CalledProcessError, e:
            msg =  "Failed to move result from %s to %s."%(tmp_outpath_this_model, outpath_this_model)
            g_params['runjob_err'].append(msg)
            g_params['runjob_err'].append(str(e)+"\n")
            pass
    modelfile = "%s/query_%d.pdb"%(outpath_this_model,modelidx)
    globalscorefile = "%s.proq3.global"%(modelfile)
    globalscore = ReadProQ3GlobalScore(globalscorefile)
    modelseqfile = "%s/query_%d.pdb.fasta"%(outpath_this_model, modelidx)
    modellength = myfunc.GetSingleFastaLength(modelseqfile)

    modelinfo = [subfoldername_this_model, str(modellength), str(runtime_in_sec)]
    if globalscore:
        modelinfo.append(str(globalscore['ProQ2']))
        modelinfo.append(str(globalscore['ProQ_Lowres']))
        modelinfo.append(str(globalscore['ProQ_Highres']))
        modelinfo.append(str(globalscore['ProQ3']))
    return modelinfo
#}}}
def RunJob(modelfile, seqfile, isRepack, isKeepFiles, targetlength, #{{{
        outpath, tmpdir, email, jobid, g_params):
    all_begin_time = time.time()

    rootname = os.path.basename(os.path.splitext(modelfile)[0])
    starttagfile   = "%s/runjob.start"%(outpath)
    runjob_errfile = "%s/runjob.err"%(outpath)
    runjob_logfile = "%s/runjob.log"%(outpath)
    finishtagfile = "%s/runjob.finish"%(outpath)
    rmsg = ""


    resultpathname = jobid

    outpath_result = "%s/%s"%(outpath, resultpathname)
    tarball = "%s.tar.gz"%(resultpathname)
    zipfile = "%s.zip"%(resultpathname)
    tarball_fullpath = "%s.tar.gz"%(outpath_result)
    zipfile_fullpath = "%s.zip"%(outpath_result)
    mapfile = "%s/seqid_index_map.txt"%(outpath_result)
    finished_model_file = "%s/finished_models.txt"%(outpath_result)
    timefile = "%s/time.txt"%(outpath_result)

    tmp_outpath_result = "%s/%s"%(tmpdir, resultpathname)
    isOK = True
    try:
        os.makedirs(tmp_outpath_result)
        isOK = True
    except OSError:
        msg = "Failed to create folder %s"%(tmp_outpath_result)
        myfunc.WriteFile(msg+"\n", runjob_errfile, "a")
        isOK = False
        pass

    try:
        os.makedirs(outpath_result)
        isOK = True
    except OSError:
        msg = "Failed to create folder %s"%(outpath_result)
        myfunc.WriteFile(msg+"\n", runjob_errfile, "a")
        isOK = False
        pass


    if isOK:
        try:
            open(finished_model_file, 'w').close()
        except:
            pass
#first getting result from caches
# cache profiles for sequences, but do not cache predictions for models
        datetime = time.strftime("%Y-%m-%d %H:%M:%S")
        rt_msg = myfunc.WriteFile(datetime, starttagfile)
# ==================================
        numModel = 0
        modelFileList = []
        if seqfile != "": # if the fasta sequence is supplied, all models should be using this sequence
            subfoldername_profile = "profile_%d"%(0)
            outpath_profile = "%s/%s"%(outpath_result, subfoldername_profile)
            CreateProfile(seqfile, outpath_profile, outpath_result, tmp_outpath_result, timefile, runjob_errfile)

            # run proq3 for models
            modelList = myfunc.ReadPDBModel(modelfile)
            numModel = len(modelList)
            for ii in xrange(len(modelList)):
                model = modelList[ii]
                tmp_model_file = "%s/query_%d.pdb"%(tmp_outpath_result, ii)
                myfunc.WriteFile(model+"\n", tmp_model_file)
                profilename = "%s/%s"%(outpath_profile, "query.fasta")
                subfoldername_this_model = "model_%d"%(ii)
                outpath_this_model = "%s/%s"%(outpath_result, subfoldername_this_model)

                modelinfo = ScoreModel(tmp_model_file, outpath_this_model, profilename,
                        outpath_result, tmp_outpath_result, timefile,
                        runjob_errfile, isRepack, isKeepFiles, targetlength)
                myfunc.WriteFile("\t".join(modelinfo)+"\n", finished_model_file, "a")
                modelFileList.append("%s/%s"%(outpath_this_model, "query_%d.pdb"%(ii)))

        else: # no seqfile supplied, sequences are obtained from the model file
            modelList = myfunc.ReadPDBModel(modelfile)
            numModel = len(modelList)
            for ii in xrange(len(modelList)):
                model = modelList[ii]
                tmp_model_file = "%s/query_%d.pdb"%(tmp_outpath_result, ii)
                myfunc.WriteFile(model+"\n", tmp_model_file)
                subfoldername_this_model = "model_%d"%(ii)
                tmp_outpath_this_model = "%s/%s"%(tmp_outpath_result, subfoldername_this_model)
                if not os.path.exists(tmp_outpath_this_model):
                    os.makedirs(tmp_outpath_this_model)
                tmp_seqfile = "%s/query.fasta"%(tmp_outpath_this_model)
                cmd = [pdb2aa_script, tmp_model_file]
                g_params['runjob_log'].append(" ".join(cmd))
                try:
                    rmsg = subprocess.check_output(cmd)
                    g_params['runjob_log'].append("extracting sequence from modelfile:\n"+rmsg+"\n")
                except subprocess.CalledProcessError, e:
                    g_params['runjob_err'].append(str(e)+"\n")
                    g_params['runjob_err'].append(rmsg + "\n")

                if rmsg != "":
                    myfunc.WriteFile(">seq\n"+rmsg.strip(),tmp_seqfile)


                subfoldername_profile = "profile_%d"%(ii)
                outpath_profile = "%s/%s"%(outpath_result, subfoldername_profile)
                CreateProfile(tmp_seqfile, outpath_profile, outpath_result, tmp_outpath_result, timefile, runjob_errfile)

                outpath_this_model = "%s/%s"%(outpath_result, subfoldername_this_model)
                profilename = "%s/%s"%(outpath_profile, "query.fasta")
                modelinfo = ScoreModel(tmp_model_file, outpath_this_model, profilename,
                        outpath_result, tmp_outpath_result, timefile,
                        runjob_errfile, isRepack, isKeepFiles, targetlength)
                myfunc.WriteFile("\t".join(modelinfo)+"\n", finished_model_file, "a")
                modelFileList.append("%s/%s"%(outpath_this_model, "query_%d.pdb"%(ii)))

        all_end_time = time.time()
        all_runtime_in_sec = all_end_time - all_begin_time

        if len(g_params['runjob_log']) > 0 :
            rt_msg = myfunc.WriteFile("\n".join(g_params['runjob_log'])+"\n", runjob_logfile, "a")
            if rt_msg:
                g_params['runjob_err'].append(rt_msg)

        datetime = time.strftime("%Y-%m-%d %H:%M:%S")
        rt_msg = myfunc.WriteFile(datetime, finishtagfile)
        if rt_msg:
            g_params['runjob_err'].append(rt_msg)

# now write the text output to a single file
        #statfile = "%s/%s"%(outpath_result, "stat.txt")
        statfile = ""
        dumped_resultfile = "%s/%s"%(outpath_result, "query.proq3.txt")
        WriteTextResultFile(dumped_resultfile, outpath_result, modelFileList,
                all_runtime_in_sec, statfile=statfile)

        # now making zip instead (for windows users)
        # note that zip rq will zip the real data for symbolic links
        os.chdir(outpath)
#             cmd = ["tar", "-czf", tarball, resultpathname]
        cmd = ["zip", "-rq", zipfile, resultpathname]
        try:
            subprocess.check_output(cmd)
        except subprocess.CalledProcessError, e:
            g_params['runjob_err'].append(str(e))
            pass


    isSuccess = False
    if (os.path.exists(finishtagfile) and os.path.exists(zipfile_fullpath)):
        isSuccess = True
        # delete the tmpdir if succeeded
        shutil.rmtree(tmpdir) #DEBUG, keep tmpdir
    else:
        isSuccess = False
        failtagfile = "%s/runjob.failed"%(outpath)
        datetime = time.strftime("%Y-%m-%d %H:%M:%S")
        rt_msg = myfunc.WriteFile(datetime, failtagfile)
        if rt_msg:
            g_params['runjob_err'].append(rt_msg)

# send the result to email
# do not sendmail at the cloud VM
    if (g_params['base_www_url'].find("bioinfo.se") != -1 and
            myfunc.IsValidEmailAddress(email)):
        from_email = "proq3@proq3.bioinfo.se"
        to_email = email
        subject = "Your result for ProQ3 JOBID=%s"%(jobid)
        if isSuccess:
            bodytext = """
Your result is ready at %s/pred/result/%s

Thanks for using ProQ3

        """%(g_params['base_www_url'], jobid)
        else:
            bodytext="""
We are sorry that your job with jobid %s is failed.

Please contact %s if you have any questions.

Attached below is the error message:
%s
            """%(jobid, contact_email, "\n".join(g_params['runjob_err']))
        g_params['runjob_log'].append("Sendmail %s -> %s, %s"% (from_email, to_email, subject)) #debug
        rtValue = myfunc.Sendmail(from_email, to_email, subject, bodytext)
        if rtValue != 0:
            g_params['runjob_err'].append("Sendmail to {} failed with status {}".format(to_email, rtValue))

    if len(g_params['runjob_err']) > 0:
        rt_msg = myfunc.WriteFile("\n".join(g_params['runjob_err'])+"\n", runjob_errfile, "w")
        return 1
    return 0
#}}}
def main(g_params):#{{{
    argv = sys.argv
    numArgv = len(argv)
    if numArgv < 2:
        PrintHelp()
        return 1

    outpath = ""
    modelfile = ""
    seqfile = ""
    tmpdir = ""
    email = ""
    jobid = ""
    isKeepFiles = "no"
    isRepack = "yes"
    targetlength = None

    i = 1
    isNonOptionArg=False
    while i < numArgv:
        if isNonOptionArg == True:
            modelfile = argv[i]
            isNonOptionArg = False
            i += 1
        elif argv[i] == "--":
            isNonOptionArg = True
            i += 1
        elif argv[i][0] == "-":
            if argv[i] in ["-h", "--help"]:
                PrintHelp()
                return 1
            elif argv[i] in ["-outpath", "--outpath"]:
                (outpath, i) = myfunc.my_getopt_str(argv, i)
            elif argv[i] in ["-tmpdir", "--tmpdir"] :
                (tmpdir, i) = myfunc.my_getopt_str(argv, i)
            elif argv[i] in ["-jobid", "--jobid"] :
                (jobid, i) = myfunc.my_getopt_str(argv, i)
            elif argv[i] in ["-fasta", "--fasta"] :
                (seqfile, i) = myfunc.my_getopt_str(argv, i)
            elif argv[i] in ["-k", "--k"] :
                (isKeepFiles, i) = myfunc.my_getopt_str(argv, i)
            elif argv[i] in ["-r", "--r"] :
                (isRepack, i) = myfunc.my_getopt_str(argv, i)
            elif argv[i] in ["-t", "--t"] :
                (targetlength, i) = myfunc.my_getopt_int(argv, i)
            elif argv[i] in ["-baseurl", "--baseurl"] :
                (g_params['base_www_url'], i) = myfunc.my_getopt_str(argv, i)
            elif argv[i] in ["-email", "--email"] :
                (email, i) = myfunc.my_getopt_str(argv, i)
            elif argv[i] in ["-q", "--q"]:
                g_params['isQuiet'] = True
                i += 1
            elif argv[i] in ["-force", "--force"]:
                g_params['isForceRun'] = True
                i += 1
            else:
                print >> sys.stderr, "Error! Wrong argument:", argv[i]
                return 1
        else:
            modelfile = argv[i]
            i += 1

    if jobid == "":
        print >> sys.stderr, "%s: jobid not set. exit"%(sys.argv[0])
        return 1

    if myfunc.checkfile(modelfile, "modelfile") != 0:
        return 1
    if outpath == "":
        print >> sys.stderr, "outpath not set. exit"
        return 1
    elif not os.path.exists(outpath):
        try:
            subprocess.check_output(["mkdir", "-p", outpath])
        except subprocess.CalledProcessError, e:
            print >> sys.stderr, e
            return 1
    if tmpdir == "":
        print >> sys.stderr, "tmpdir not set. exit"
        return 1
    elif not os.path.exists(tmpdir):
        try:
            subprocess.check_output(["mkdir", "-p", tmpdir])
        except subprocess.CalledProcessError, e:
            print >> sys.stderr, e
            return 1

    g_params['debugfile'] = "%s/debug.log"%(outpath)

    if not os.path.exists(path_profile_cache):
        os.makedirs(path_profile_cache)

    g_params['proq3opt']  = "-r %s -k %s "%(isRepack, isKeepFiles)
    if targetlength != None:
        g_params['proq3opt'] += "-t %d"%(targetlength)

    return RunJob(modelfile, seqfile, isRepack, isKeepFiles, targetlength,
            outpath, tmpdir, email, jobid, g_params)

#}}}

def InitGlobalParameter():#{{{
    g_params = {}
    g_params['isQuiet'] = True
    g_params['runjob_log'] = []
    g_params['runjob_err'] = []
    g_params['isForceRun'] = False
    g_params['base_www_url'] = ""
    g_params['proq3opt']  = ""
    return g_params
#}}}
if __name__ == '__main__' :
    g_params = InitGlobalParameter()
    sys.exit(main(g_params))
