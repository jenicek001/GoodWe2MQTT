#/bin/bash

# check if there is user goodwe2mqtt, if not, create user and group
if ! id -u goodwe2mqtt >/dev/null 2>&1; then
    echo "user goodwe2mqtt not found, creating user and group"
    groupadd goodwe2mqtt
    useradd -g goodwe2mqtt goodwe2mqtt
else
    echo "user goodwe2mqtt found"
fi

# check if venv is created
if [ ! -d "venv" ]; then
    echo "venv not found, creating venv"
    python3 -m venv venv

    # activate venv
    source venv/bin/activate

    # upgrade pip
    pip install --upgrade pip

    # install requirements
    pip install -r requirements.txt

    # deactivate venv
    deactivate

    echo "venv created"
else
    echo "venv found"
fi

# check if there is a directory for logging /var/log/goodwe2mqtt and owned by goodwe2mqtt
if [ ! -d "/var/log/goodwe2mqtt" ]; then
    echo "directory /var/log/goodwe2mqtt not found, creating directory"
    mkdir /var/log/goodwe2mqtt
    chown goodwe2mqtt:goodwe2mqtt /var/log/goodwe2mqtt
else
    echo "directory /var/log/goodwe2mqtt found"
fi

# check if service is installed
if [ ! -f "/etc/systemd/system/goodwe2mqtt.service" ]; then
    echo "service not found, installing service"

    # copy service file to systemd
    cp goodwe2mqtt.service /etc/systemd/system/

    # reload systemd
    systemctl daemon-reload

    # enable service
    systemctl enable goodwe2mqtt.service
else
    echo "service found - stopping service"
    systemctl stop goodwe2mqtt.service
fi

# copy whole directory to /opt
cp -r . /opt/goodwe2mqtt

# change owner of /opt/goodwe2mqtt to goodwe2mqtt
chown -R goodwe2mqtt:goodwe2mqtt /opt/goodwe2mqtt

# make goodwe2mqtt.sh executable
chmod +x /opt/goodwe2mqtt/goodwe2mqtt.sh

systemctl start goodwe2mqtt.service
sleep 5
systemctl status goodwe2mqtt.service

# check return code
if [ $? -eq 0 ]; then
    echo "Installation successful"
else
    echo "Installation failed"
fi
