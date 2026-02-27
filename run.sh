#!/bin/bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

source /etc/profile.d/modules.sh

cd ${DIR}
module load python3
./parse.py
./parse.py 2
module reset 

scp *_avery.{pdf,png} uaf-10:~/public_html/hpg/usage/
scp *_avery-b.{pdf,png} uaf-10:~/public_html/hpg/usage_burst/

scp data_avery.json data_avery-b.json uaf-10:~/public_html/hpg/usage/
scp dashboard/index.html uaf-10:~/public_html/hpg/usage/

# Deploy to GitHub Pages
module load git
./deploy_pages.sh >> $HOME/scron/logs/testlogs.txt 2>&1 || true

echo "scrontab ran at timestamp: `date`" >> $HOME/scron/logs/testlogs.txt
