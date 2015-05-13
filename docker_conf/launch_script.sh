#!/bin/bash
echo "launch_script.sh start"
service nginx start
uwsgi ./conf/ImageResizingServerApp.ini