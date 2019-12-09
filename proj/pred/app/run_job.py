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
import json
import webserver_common
os.environ["PATH"] += os.pathsep + "/usr/local/bin" # this solved the problem for CentOS6.4
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

# note that here the url should be without http://

usage_short="""
Usage: %s dumped-model-file [-fasta seqfile]
       %s -jobid JOBID -outpath DIR -tmpdir DIR
       %s -email EMAIL -baseurl BASE_WWW_URL
       %s [-force]
"""%(progname, wspace, wspace, wspace)

usage_ext="""\
Description:
    run job

OPTIONS:
  -force        Do not use cahced result
  -h, --help    Print this help message and exit

Created 2016-02-02, updated 2017-10-09, Nanjiang Shu
"""
usage_exp="""
Examples:
    %s /data3/tmp/tmp_dkgSD/query.pdb -outpath /data3/result/rst_mXLDGD -tmpdir /data3/tmp/tmp_dkgSD
"""%(progname)

def PrintHelp(fpout=sys.stdout):#{{{
    print(usage_short, file=fpout)
    print(usage_ext, file=fpout)
    print(usage_exp, file=fpout)#}}}

def CreateProfile(seqfile, outpath_profile, outpath_result, tmp_outpath_result, timefile, runjob_errfile):#{{{
    (seqid, seqanno, seq) = myfunc.ReadSingleFasta(seqfile)
    subfoldername_profile = os.path.basename(outpath_profile)
    tmp_outpath_profile = "%s/%s"%(tmp_outpath_result, subfoldername_profile)
    isSkip = False
    rmsg = ""
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
        cmdline = " ".join(cmd)
        #os.system("%s >> %s 2>&1"%(cmdline, runjob_errfile)) #DEBUG
        try:
            rmsg = subprocess.check_output(cmd)
            g_params['runjob_log'].append("profile_building:\n"+rmsg+"\n")
        except subprocess.CalledProcessError as e:
            g_params['runjob_err'].append(str(e)+"\n")
            g_params['runjob_err'].append("cmdline: "+cmdline+"\n")
            g_params['runjob_err'].append("profile_building:\n"+rmsg + "\n")
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
            except subprocess.CalledProcessError as e:
                msg =  "Failed to run get profile for the target sequence %s"%(seq)
                g_params['runjob_err'].append(msg)
                g_params['runjob_err'].append(str(e)+"\n")
                pass

            if isCmdSuccess and webserver_common.IsFrontEndNode(g_params['base_www_url']):

                # make zip folder for the cached profile
                cwd = os.getcwd()
                os.chdir(subfolder_profile_cache)
                cmd = ["zip", "-rq", "%s.zip"%(md5_key), md5_key]
                try:
                    subprocess.check_output(cmd)
                except subprocess.CalledProcessError as e:
                    g_params['runjob_err'].append(str(e))
                    pass
                os.chdir(cwd)


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
def GetProQ3Option(query_para):#{{{
    """Return the proq3opt in list
    """
    yes_or_no_opt = {}
    for item in ['isDeepLearning', 'isRepack', 'isKeepFiles']:
        if query_para[item]:
            yes_or_no_opt[item] = "yes"
        else:
            yes_or_no_opt[item] = "no"

    proq3opt = [
            "-r", yes_or_no_opt['isRepack'],
            "-deep", yes_or_no_opt['isDeepLearning'],
            "-k", yes_or_no_opt['isKeepFiles'],
            "-quality", query_para['method_quality'],
            "-output_pdbs", "yes"         #always output PDB file (with proq3 written at the B-factor column)
            ]
    if 'targetlength' in query_para:
        proq3opt += ["-t", str(query_para['targetlength'])]

    return proq3opt

#}}}
def ScoreModel(query_para, model_file, outpath_this_model, profilename, outpath_result, #{{{
        tmp_outpath_result, timefile, runjob_errfile): 
    subfoldername_this_model = os.path.basename(outpath_this_model)
    modelidx = int(subfoldername_this_model.split("model_")[1])
    try:
        method_quality = query_para['method_quality']
    except KeyError:
        method_quality = 'sscore'
    rmsg = ""
    tmp_outpath_this_model = "%s/%s"%(tmp_outpath_result, subfoldername_this_model)
    proq3opt = GetProQ3Option(query_para)
    cmd = [runscript, "-profile", profilename,  "-outpath",
            tmp_outpath_this_model, model_file
            ] + proq3opt
    g_params['runjob_log'].append(" ".join(cmd))
    cmdline = " ".join(cmd)
    begin_time = time.time()
    try:
        rmsg = subprocess.check_output(cmd)
        g_params['runjob_log'].append("model scoring:\n"+rmsg+"\n")
    except subprocess.CalledProcessError as e:
        g_params['runjob_err'].append(str(e)+"\n")
        g_params['runjob_err'].append("cmdline: "+ cmdline + "\n")
        g_params['runjob_err'].append("model scoring:\n" + rmsg + "\n")
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
        except subprocess.CalledProcessError as e:
            msg =  "Failed to move result from %s to %s."%(tmp_outpath_this_model, outpath_this_model)
            g_params['runjob_err'].append(msg)
            g_params['runjob_err'].append(str(e)+"\n")
            pass
    modelfile = "%s/query_%d.pdb"%(outpath_this_model,modelidx)
    globalscorefile = "%s.proq3.%s.global"%(modelfile, method_quality)
    if not os.path.exists(globalscorefile):
        globalscorefile = "%s.proq3.global"%(modelfile)
    (globalscore, itemList) = webserver_common.ReadProQ3GlobalScore(globalscorefile)
    modelseqfile = "%s/query_%d.pdb.fasta"%(outpath_this_model, modelidx)
    modellength = myfunc.GetSingleFastaLength(modelseqfile)

    modelinfo = [subfoldername_this_model, str(modellength), str(runtime_in_sec)]
    if globalscore:
        for i in range(len(itemList)):
            modelinfo.append(str(globalscore[itemList[i]]))
    return modelinfo
#}}}
def RunJob(modelfile, seqfile, outpath, tmpdir, email, jobid, g_params):#{{{
    all_begin_time = time.time()

    rootname = os.path.basename(os.path.splitext(modelfile)[0])
    starttagfile   = "%s/runjob.start"%(outpath)
    runjob_errfile = "%s/runjob.err"%(outpath)
    runjob_logfile = "%s/runjob.log"%(outpath)
    finishtagfile = "%s/runjob.finish"%(outpath)
    rmsg = ""

    query_parafile = "%s/query.para.txt"%(outpath)
    query_para = {}
    content = myfunc.ReadFile(query_parafile)
    if content != "":
        query_para = json.loads(content)

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
    if os.path.exists(tmp_outpath_result):
        shutil.rmtree(tmp_outpath_result)
    try:
        os.makedirs(tmp_outpath_result)
        isOK = True
    except OSError:
        msg = "Failed to create folder %s"%(tmp_outpath_result)
        myfunc.WriteFile(msg+"\n", runjob_errfile, "a")
        isOK = False
        pass

    if os.path.exists(outpath_result):
        shutil.rmtree(outpath_result)
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
        webserver_common.WriteDateTimeTagFile(starttagfile, runjob_logfile, runjob_errfile)
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
            for ii in range(len(modelList)):
                model = modelList[ii]
                tmp_model_file = "%s/query_%d.pdb"%(tmp_outpath_result, ii)
                myfunc.WriteFile(model+"\n", tmp_model_file)
                profilename = "%s/%s"%(outpath_profile, "query.fasta")
                subfoldername_this_model = "model_%d"%(ii)
                outpath_this_model = "%s/%s"%(outpath_result, subfoldername_this_model)

                modelinfo = ScoreModel(query_para, tmp_model_file, outpath_this_model, profilename,
                        outpath_result, tmp_outpath_result, timefile,
                        runjob_errfile)
                myfunc.WriteFile("\t".join(modelinfo)+"\n", finished_model_file, "a")
                modelFileList.append("%s/%s"%(outpath_this_model, "query_%d.pdb"%(ii)))

        else: # no seqfile supplied, sequences are obtained from the model file
            modelList = myfunc.ReadPDBModel(modelfile)
            numModel = len(modelList)
            for ii in range(len(modelList)):
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
                except subprocess.CalledProcessError as e:
                    g_params['runjob_err'].append(str(e)+"\n")
                    g_params['runjob_err'].append(rmsg + "\n")

                if rmsg != "":
                    myfunc.WriteFile(">seq\n"+rmsg.strip(),tmp_seqfile)


                subfoldername_profile = "profile_%d"%(ii)
                outpath_profile = "%s/%s"%(outpath_result, subfoldername_profile)
                CreateProfile(tmp_seqfile, outpath_profile, outpath_result, tmp_outpath_result, timefile, runjob_errfile)

                outpath_this_model = "%s/%s"%(outpath_result, subfoldername_this_model)
                profilename = "%s/%s"%(outpath_profile, "query.fasta")
                modelinfo = ScoreModel(query_para, tmp_model_file, outpath_this_model, profilename,
                        outpath_result, tmp_outpath_result, timefile,
                        runjob_errfile)
                myfunc.WriteFile("\t".join(modelinfo)+"\n", finished_model_file, "a")
                modelFileList.append("%s/%s"%(outpath_this_model, "query_%d.pdb"%(ii)))

        all_end_time = time.time()
        all_runtime_in_sec = all_end_time - all_begin_time

        if len(g_params['runjob_log']) > 0 :
            rt_msg = myfunc.WriteFile("\n".join(g_params['runjob_log'])+"\n", runjob_logfile, "a")
            if rt_msg:
                g_params['runjob_err'].append(rt_msg)

        webserver_common.WriteDateTimeTagFile(finishtagfile, runjob_logfile, runjob_errfile)
# now write the text output to a single file
        #statfile = "%s/%s"%(outpath_result, "stat.txt")
        statfile = ""
        dumped_resultfile = "%s/%s"%(outpath_result, "query.proq3.txt")
        proq3opt = GetProQ3Option(query_para)
        webserver_common.WriteProQ3TextResultFile(dumped_resultfile, query_para, modelFileList,
                all_runtime_in_sec, g_params['base_www_url'], proq3opt, statfile=statfile)

        # now making zip instead (for windows users)
        # note that zip rq will zip the real data for symbolic links
        os.chdir(outpath)
#             cmd = ["tar", "-czf", tarball, resultpathname]
        cmd = ["zip", "-rq", zipfile, resultpathname]
        try:
            subprocess.check_output(cmd)
        except subprocess.CalledProcessError as e:
            g_params['runjob_err'].append(str(e))
            pass


    isSuccess = False
    if (os.path.exists(finishtagfile) and os.path.exists(zipfile_fullpath)):
        isSuccess = True
        flist = glob.glob("%s/*.out"%(tmpdir))
        if len(flist)>0:
            outfile_runscript = flist[0]
        else:
            outfile_runscript = ""
        if os.path.exists(outfile_runscript):
            shutil.move(outfile_runscript, outpath)
        # delete the tmpdir if succeeded
        shutil.rmtree(tmpdir) #DEBUG, keep tmpdir
    else:
        isSuccess = False
        failedtagfile = "%s/runjob.failed"%(outpath)
        webserver_common.WriteDateTimeTagFile(failedtagfile, runjob_logfile, runjob_errfile)

# send the result to email
# do not sendmail at the cloud VM
    if ( webserver_common.IsFrontEndNode(g_params['base_www_url']) and
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
                print("Error! Wrong argument:", argv[i], file=sys.stderr)
                return 1
        else:
            modelfile = argv[i]
            i += 1

    if jobid == "":
        print("%s: jobid not set. exit"%(sys.argv[0]), file=sys.stderr)
        return 1

    if myfunc.checkfile(modelfile, "modelfile") != 0:
        return 1
    if outpath == "":
        print("outpath not set. exit", file=sys.stderr)
        return 1
    elif not os.path.exists(outpath):
        try:
            subprocess.check_output(["mkdir", "-p", outpath])
        except subprocess.CalledProcessError as e:
            print(e, file=sys.stderr)
            return 1
    if tmpdir == "":
        print("tmpdir not set. exit", file=sys.stderr)
        return 1
    elif not os.path.exists(tmpdir):
        try:
            subprocess.check_output(["mkdir", "-p", tmpdir])
        except subprocess.CalledProcessError as e:
            print(e, file=sys.stderr)
            return 1

    g_params['debugfile'] = "%s/debug.log"%(outpath)

    if not os.path.exists(path_profile_cache):
        os.makedirs(path_profile_cache)


    return RunJob(modelfile, seqfile, outpath, tmpdir, email, jobid, g_params)

#}}}

def InitGlobalParameter():#{{{
    g_params = {}
    g_params['isQuiet'] = True
    g_params['runjob_log'] = []
    g_params['runjob_err'] = []
    g_params['isForceRun'] = False
    g_params['base_www_url'] = ""
    return g_params
#}}}
if __name__ == '__main__' :
    g_params = InitGlobalParameter()
    sys.exit(main(g_params))
