# `srun` examples:

    srun --partition=gpu --cpus=8 --gpus=1 --mem=16gb --constraint=a100 --pty bash -i
    srun --partition=gpu          --gpus=1 --mem=16gb --constraint=a100 --pty bash -i

    sacct -n -a -S $(date +%F) -q avery --format=User%20,JobID%30,JobName%30,Partition%30,State,Submit,Start,End,ElapsedRaw,AllocCPUs > data.txt

Printing out # of currently running avery CPUs:

    squeue --qos=avery -o "%.12C" -h -t R | awk '{total += $1} END {print total}'
