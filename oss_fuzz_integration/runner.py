# Copyright 2021 Fuzz Introspector Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import sys
import signal
import argparse
import subprocess
import sys
import json
import threading
import shutil
from typing import Optional


def download_public_corpus(
    project_name,
    fuzzer_name,
    target_zip
):
    OSS_FUZZ_PUBLIC_CORPUS = "https://storage.googleapis.com/%s-backup.clusterfuzz-external.appspot.com/corpus/libFuzzer/%s_%s/public.zip"
    download_url = OSS_FUZZ_PUBLIC_CORPUS % (project_name, project_name, fuzzer_name)

    cmd = f"wget {download_url}"
    if target_zip:
        cmd += f" -O {target_zip}"

    subprocess.check_call(cmd, shell=True)


def download_full_public_corpus(project_name, target_corpus_dir: None):
    # First build the project which we use to identify fuzzers
    build_project(project_name, to_clean = True)

    fuzzers = get_fuzzers(project_name)
    for fuzzer in fuzzers:
        download_public_corpus(project_name, fuzzer, f"corpus-{project_name}-{fuzzer}.zip")

    if not target_corpus_dir:
        target_corpus_dir = "mycorpus"

    if not os.path.isdir(target_corpus_dir):
        os.mkdir(target_corpus_dir)

    for fuzzer in fuzzers:
        target_fuzzer_dir = os.path.join(target_corpus_dir, fuzzer)
        if not os.path.isdir(target_fuzzer_dir):
            os.mkdir(target_fuzzer_dir)

        target_zip = f"corpus-{project_name}-{fuzzer}.zip"
        subprocess.check_call(f"unzip {target_zip} -d {target_fuzzer_dir}/", shell=True)


def build_project(
    project_name,
    sanitizer = None,
    to_clean = False
):
    """Wrapper for building projects using OSS-Fuzz's helper.py"""
    cmd = ["python3", "infra/helper.py", "build_fuzzers"]
    if sanitizer is not None:
        cmd.append("--sanitizer")
        cmd.append(sanitizer)
    if to_clean:
        cmd.append("--clean")
    cmd.append(project_name)

    try:
        subprocess.check_call(" ".join(cmd), shell=True)
    except:
        print("Building project failed")
        exit(1)


def get_fuzzers(project_name):
    execs = []
    for l in os.listdir("build/out/%s"%(project_name)):
        print("Checking %s"%(l))
        if l in {'llvm-symbolizer', 'sanitizer_with_fuzzer.so'}:
            continue
        if l.startswith('jazzer_'):
            continue
        complete_path = os.path.join("build/out/%s"%(project_name), l)
        executable = (os.path.isfile(complete_path) and os.access(complete_path, os.X_OK))
        if executable:
            execs.append(l)
    print("Fuzz targets: %s"%(str(execs)))
    return execs


def get_next_corpus_dir():
    max_idx = -1
    for f in os.listdir("."):
        if "corpus-" in f:
            try:
                idx = int(f[len("corpus-"):])
                if idx > max_idx: 
                    max_idx = idx
            except:
                None
    return "corpus-%d"%(max_idx+1)


def get_recent_corpus_dir():
    max_idx = -1
    for f in os.listdir("."):
        if "corpus-" in f:
            try:
                idx = int(f[len("corpus-"):])
                if idx > max_idx: 
                    max_idx = idx
            except:
                None
    return "corpus-%d"%(max_idx)


def run_all_fuzzers(project_name, fuzztime, job_count, corpus_dir):
    # First get all fuzzers names
    fuzzer_names = get_fuzzers(project_name)

    user_provided_corpus = corpus_dir is not None

    if corpus_dir is None:
        corpus_dir = get_next_corpus_dir()
    if not os.path.isdir(corpus_dir):
        os.mkdir(corpus_dir)

    for f in fuzzer_names:
        print("Running %s"%(f))
        target_corpus = "./%s/%s"%(corpus_dir, f)
        target_crashes = "./%s/%s"%(corpus_dir, "crashes_%s"%(f))
        if not os.path.isdir(target_corpus):
            os.mkdir(target_corpus)
        if not os.path.isdir(target_crashes):
            os.mkdir(target_crashes)

        cmd = [
            "python3",
            "./infra/helper.py",
            "run_fuzzer",
            "--corpus-dir=%s"%(target_corpus),
        ]
        # We must set this to avoid triggering
        # https://github.com/google/oss-fuzz/blob/05b2e6dd5e3c08a5d11fa7a46f3ed8f555ff9a7f/infra/base-images/base-runner/run_fuzzer#L29-L36
        if user_provided_corpus:
            cmd.append(f"-e=\"CORPUS_DIR=/tmp/{f}_corpus\"")
        cmd += [
            "%s"%(project_name),
            "%s"%(f),
            "--",
            "-max_total_time=%d"%(fuzztime),
            "-detect_leaks=0"
        ]


        # If job count is non-standard, apply here
        if job_count != 1:
            # import psutil here to avoid having to install package
            # when not using this feature
            import psutil
            #Utilize half cores if max is indicated
            max_core_num = round(psutil.cpu_count()/2)
            if job_count == 0 or job_count > max_core_num:
                job_count = max_core_num

            print("Non-standard job count. Running: %d jobs"%(job_count))
            cmd.append("-workers=%d"%(job_count))
            cmd.append("-jobs=%d"%(job_count))


        print("Runing command: %s"%(" ".join(cmd)))
        try:
            subprocess.check_call(" ".join(cmd), shell=True)
            print("Execution finished without exception")
        except:
            print("Executing finished with exception")

        # Now check if there are any crash files.
        for l in os.listdir("."):
            if "crash-" in l or "leak-" in l:
                shutil.move(l, target_crashes)


def get_coverage(project_name, corpus_dir):
    #1 Find all coverage reports
    if corpus_dir is None:
        corpus_dir = get_recent_corpus_dir()

    #2 Copy them into the right folder
    for f in os.listdir(corpus_dir):
        if os.path.isdir("build/corpus/%s/%s"%(project_name, f)):
            shutil.rmtree("build/corpus/%s/%s"%(project_name, f))
        shutil.copytree(
            os.path.join(corpus_dir, f),
            "build/corpus/%s/%s"%(project_name, f)
            )

    #3 run coverage command
    cmd = [
        "python3",
        "infra/helper.py",
        "coverage",
        "--port ''",
        "--no-corpus-download",
        project_name
    ]
    try:
        subprocess.check_call(
            " ".join(cmd),
            shell=True
        )
    except:
        print("Could not run coverage reports")


    print("Copying report")
    # Delete the existing coverage report
    if os.path.isdir("./%s/report"%(corpus_dir)):
        shutil.rmtree("./%s/report"%(corpus_dir))
    if os.path.isdir("./%s/report_target"%(corpus_dir)):
        shutil.rmtree("./%s/report_target"%(corpus_dir))

    shutil.copytree(
        "./build/out/%s/report"%(project_name),
        "./%s/report"%(corpus_dir)
    )
    shutil.copytree(
        "./build/out/%s/report_target"%(project_name),
        "./%s/report_target"%(corpus_dir)
    )
    try:
        summary_file = "build/out/%s/report/linux/summary.json"%(project_name)
        with open(summary_file, "r") as fj:
            content = json.load(fj)
            for dd in content['data']:
                if "totals" in dd:
                    if "lines" in dd['totals']:
                        print("lines: %s"%(dd['totals']['lines']['percent']))
                        lines_percent = dd['totals']['lines']['percent']        
                        print("lines_percent: %s"%(lines_percent))
                        return lines_percent
    except:
        return None

    # Copy the report into the corpus directory
    print("Finished")


def setup_next_corpus_dir(project_name):
    fuzzer_names = get_fuzzers(project_name)
    corpus_dir = get_next_corpus_dir()
    if not os.path.isdir(corpus_dir):
        os.mkdir(corpus_dir)

    return corpus_dir


def complete_coverage_check(
    project_name: str,
    fuzztime: int,
    job_count: int,
    corpus_dir: Optional[str],
    download_public_corpus: bool
):
    build_project(project_name, to_clean=True)

    if download_public_corpus:
        corpus_dir = setup_next_corpus_dir(project_name)
        download_full_public_corpus(project_name, corpus_dir)

    run_all_fuzzers(project_name, fuzztime, job_count, corpus_dir)
    build_project(project_name, sanitizer="coverage")
    percent = get_coverage(project_name, corpus_dir)
 
    return percent

def introspector_run(
    project_name: str,
    fuzztime: int,
    job_count: int,
    corpus_dir: Optional[str],
    port: int,
    download_public_corpus: bool
):
    complete_coverage_check(project_name, fuzztime, job_count, corpus_dir, download_public_corpus)
    
    # Build sanitizers with introspector
    build_project(project_name, sanitizer="introspector") 

    # get the latest corpus
    latest_corpus_dir = get_recent_corpus_dir()

    # copy over inpsoector and coverage reports

    # copy over reports:
    # - introspector
    # - project coverage
    # - per-fuzzer coverage
    if os.path.isdir(os.path.join(latest_corpus_dir, "inspector-report")):
        shutil.rmtree(os.path.join(latest_corpus_dir, "inspector-report"))

    shutil.copytree("./build/out/%s/inspector"%(project_name), os.path.join(latest_corpus_dir, "inspector-report"))
    shutil.copytree(os.path.join(latest_corpus_dir, "report"), os.path.join(latest_corpus_dir, "inspector-report", "covreport"))

    for target_coverage_dir in os.listdir(os.path.join(latest_corpus_dir, "report_target")):
        shutil.copytree(
            os.path.join(latest_corpus_dir, "report_target", target_coverage_dir),
            os.path.join(latest_corpus_dir, "inspector-report", "covreport", target_coverage_dir)
        )

    # start webserver
    cmd = "python3 -m http.server %d --directory %s"%(port, os.path.join(latest_corpus_dir, "inspector-report"))
    print("The following command is about to be run to start a webserver: %s"%(cmd))
    subprocess.check_call(cmd, shell=True)


def get_single_cov(project, target, corpus_dir):
    print("Building single project")
    build_proj_with_coverage(project)

    cmd = [
        "python3",
        "infra/helper.py",
        "coverage",
        "--no-corpus-download",
        "--fuzz-target",
        target,
        "--corpus-dir",
        corpus_dir,
        project_name
    ]
    try:
        subprocess.check_call(" ".join(cmd))
    except:
        print("Could not run coverage reports")


def get_cmdline_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(dest="command")

    coverage_parser = subparsers.add_parser("coverage")
    coverage_parser.add_argument(
        "project",
        metavar="P",
        help="Name of project to run"
    )
    coverage_parser.add_argument(
        "fuzztime",
        metavar="T",
        help="Number of seconds to run fuzzers for",
        type=int
    )
    coverage_parser.add_argument(
        "--jobs",
        type=int,
        help="Number of jobs to run in parallel. Zero indicates max count (half CPU cores)",
        default=1
    )
    coverage_parser.add_argument(
        "--corpus-dir",
        type=str,
        help="directory with corpus for the project",
        default=None
    )
    coverage_parser.add_argument(
        "--download-public-corpus",
        action="store_true",
        help="if set, will download public corpus",
        default=False
    )

    introspector_parser = subparsers.add_parser("introspector")
    introspector_parser.add_argument(
        "project",
        metavar="P",
        help="Name of project to run"
    )
    introspector_parser.add_argument(
        "fuzztime",
        metavar="T",
        help="Number of seconds to run fuzzers for",
        type=int
    )
    introspector_parser.add_argument(
        "--jobs",
        type=int,
        help="Number of jobs to run in parallel. Zero indicates max count (half CPU cores)",
        default=1
    )
    introspector_parser.add_argument(
        "--corpus-dir",
        type=str,
        help="directory with corpus for the project",
        default=None
    )
    introspector_parser.add_argument(
        "--port",
        type=int,
        default=8008
    )
    introspector_parser.add_argument(
        "--download-public-corpus",
        action="store_true",
        help="if set, will download public corpus",
        default=False
    )

    download_corpus_parser = subparsers.add_parser("download-corpus")
    download_corpus_parser.add_argument(
        "project",
        help="name of project"
    )
    return parser

if __name__ == "__main__":
    parser = get_cmdline_parser()
    args = parser.parse_args()

    if args.command == "coverage":
        print("Getting full coverage:")
        print("  project = %s"%(args.project))
        print("  fuzztime = %d"%(args.fuzztime))
        print("  jobs = %d"%(args.jobs))
        complete_coverage_check(
            args.project,
            args.fuzztime,
            args.jobs,
            args.corpus_dir,
            args.download_public_corpus
        )
    elif args.command == "introspector":
        print("Running full")
        introspector_run(
            args.project,
            args.fuzztime,
            args.jobs,
            args.corpus_dir,
            args.port,
            args.download_public_corpus
        )
    elif args.command == "download-corpus":
        download_full_public_corpus(args.project)
