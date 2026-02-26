#!/bin/bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

source /etc/profile.d/modules.sh

cd ${DIR}

# ~/librarian/drain/run.sh
sh collect_data.sh
module load python
python plot_data.py
scp plot.png uaf-2:~/public_html/hpg/drain;
scp drain_data.json uaf-10:~/public_html/hpg/usage/
