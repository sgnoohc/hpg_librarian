# `srun` examples:

    srun --partition=gpu --cpus=8 --gpus=1 --mem=16gb --constraint=a100 --pty bash -i
    srun --partition=gpu          --gpus=1 --mem=16gb --constraint=a100 --pty bash -i
# hpg_librarian
