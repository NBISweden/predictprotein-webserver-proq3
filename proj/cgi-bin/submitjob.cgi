#!/usr/bin/perl -w
#use lib '/usr/lib/perl5/5.6.1/';
use CGI qw(:standard); 
use CGI qw(:cgi-lib); 
use CGI qw(:upload); 

use CGI::Carp 'fatalsToBrowser';#debug nanjiang
use POSIX qw(strftime);

use Fcntl ':flock';
use Cwd 'abs_path'; 
use File::Basename;
use File::Spec;
use File::Temp;
use JSON;

sub WriteFile{#{{{ content outfile Write File
    my $content = shift;
    my $outfile = shift;
    open(OUT,">$outfile");
    print OUT $content;
    close(OUT);
}#}}}

my $rundir = dirname(abs_path($0));
my $basedir = abs_path("$rundir/../pred");
my $path_result = "$basedir/static/result";
my $submitjoblogfile = "$basedir/static/log/submitted_seq.log";

my $hostname_of_the_computer = `hostname` ;
my $date = localtime();
my $output_str = "";
my $myemail="nanjiang.shu\@scilifelab.se";

print header();
print start_html(-title => "ProQ3 Submission",
    -author => "nanjiang.shu\@scilifelab.se",
    -meta   => {'keywords'=>''});

if(!param())
{
    print "<pre>\n";
    print "usage: curl submitjob.cgi -d structure=structure -d email -d targetseq=seq -d deep=yes_or_no\n\n";
    print "       or in the browser\n\n";
    print "       submitjob.cgi?email=email&targetseq=seq&structure=structure&deep=yes_or_no\n\n";
    print "Examples:\n";
    print "       submitjob.cgi?email=someone\@domain.com&targetseq=AATT&structure=xxx&deep=yes\n";
    print "</pre>\n";
    print end_html();
}

if (param()) 
{
    my $targetseq = "";
    my $name = "";
    my $email = "";
    my $structure = "";
    my $method_quality = "";
    my $host = "";
    my $client_ip = $ENV{'REMOTE_ADDR'};
    my $method_submission = "cgi";
    my $isDeepLearning = JSON::true;
    my $yes_or_no_deeplearning = "yes";

    $targetseq = param('targetseq');
    $targetseq=~s/\n//g;
    $targetseq=~s/\s+//g;
    $name = param('name');      # Title for CAMEO
    $email = param('email');    # email of the submitter
    $host = param('host');      # IP address of the submitter
    $method_quality = param('method_quality');  # method_quality for PROQ3D
    $structure = param('structure');    # structure info in PDB format
    $yes_or_no_deeplearning = param('deep');    # structure info in PDB format


    if(length($structure)<1)
    {
        print 'Error: structure is not provided. Exit!';
        exit;
    }

    if ($method_quality eq ""){
        $method_quality = "sscore";
    }

    if ($yes_or_no_deeplearning  eq "yes" or $yes_or_no_deeplearning eq ""){
        $isDeepLearning = JSON::true;
    }else{
        $isDeepLearning = JSON::false;
    }

    # create the job folder 
    my $rstdir = File::Temp::tempdir("$path_result/rst_XXXXXX", CLEANUP=>0);
    `chmod 755 $rstdir`;
    my $jobid = basename($rstdir);

    my $description = "query";
    if ($name ne ""){
        $description = $name;
    }

    my $jobinfofile = "$rstdir/jobinfo";
    my $rawseqfile = "$rstdir/query.raw.fa";
    my $seqfile = "$rstdir/query.fa";
    my $modelfile = "$rstdir/query.pdb";
    my $rawmodelfile = "$rstdir/query.raw.pdb";
    my $query_parafile = "$rstdir/query.para.txt";

    my $nummodel = 1;
    my $length_rawmodel = length($structure);

    my $isCAMEOtarget = 0;
    if ($email =~ /proteinmodelportal\.org/){
        $isCAMEOtarget = 1;
        WriteFile("CAMEO", "$rstdir/submitter.txt");
    }

    # write data of submitted query to rstdir
    if ($targetseq ne ""){
        WriteFile(">$description\n$targetseq\n", $rawseqfile);
        WriteFile(">$description\n$targetseq\n", $seqfile);
    }
    if ($structure ne ""){
        WriteFile($structure, $rawmodelfile);
        my $cnt = `cat $rawmodelfile | grep ENDMDL | wc -l`;
        if ($cnt > 0){
            $nummodel = $cnt;
            WriteFile($structure, $modelfile);
        }else{
            my $n_structure = "MODEL 1\n$structure\nENDMDL\n";
            WriteFile($n_structure, $modelfile);
        }
    }
    my $submit_date = strftime "%Y-%m-%d %H:%M:%S", localtime;
    my $jobinfo = "$submit_date\t$jobid\t$client_ip\t$nummodel\t$length_rawmodel\t$name\t$email\t$method_submission";
    WriteFile($jobinfo, $jobinfofile);


    my $loginfo = "$submit_date\t$jobid\t$client_ip\t$nummodel\t$length_rawmodel\t$name\t$email\t$method_submission";

    open(OUT, ">>$submitjoblogfile") || die;
    flock(OUT, 2) || die;
    print OUT "$loginfo\n";
    close(OUT);

    my %query_para = (
        'isDeepLearning' => $isDeepLearning,
        'isKeepFiles' => JSON::true,
        'isRepack' => JSON::true,
        'isForceRun' => JSON::false,
        'name_software' => 'proq3', 
        'method_quality' => $method_quality,
        'isOutputPDB' => JSON::true
    );
    my $json_para_str = encode_json \%query_para;

    WriteFile($json_para_str, $query_parafile);

    print "Your query has been submitted successfully with jobid = $jobid";
    WriteFile($submit_date, "$path_result/static/log/lastsubmission.txt");
    print end_html();
}
