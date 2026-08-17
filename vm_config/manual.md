# Staff Manual of VM Image

## Preprocess

1. Download the image of Ubuntu 22.04 LTS and install it on VMWare Workstation.
    - assuming `cwd` of the host machine to be the root directory of this repository;
    - assuming the VM file to be under `/app/VM`;
    - assuming username and password to be `user` and `password`; don't forget to tick 'Log in automatically';

2. (GUEST) CHANGE THE DISPLAY SYSTEM FROM WAYLAND TO X11

    ```shell
    sudo sed -i 's/^#WaylandEnable=false/WaylandEnable=false/' /etc/gdm3/custom.conf
    ```

    and restart the guest machine.

3. (GUEST) Disable options of 'Blank Screen':

    ```shell
    gsettings set org.gnome.desktop.session idle-delay 0
    gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing'
    ```

4. (GUEST) Change sources of `apt` and install `vm-tools` if necessary:

    ```shell
    sudo sed -i "s/cn\.//g" /etc/apt/sources.list
    sudo apt update
    sudo apt install open-vm-tools-desktop
    ```

5. (GUEST) Install `pip` and symlink for `python`:

    ```shell
    sudo apt install python-is-python3
    sudo apt install python3-pip
    ```

## Applications
### ChimeraX

1. (GUEST) Download `ucsf-chimerax_1.9ubuntu22.04_amd64.deb` at [Web Browser](https://www.cgl.ucsf.edu/chimerax/cgi-bin/secure/chimerax-get.py?file=1.9/ubuntu-22.04/ucsf-chimerax_1.9ubuntu22.04_amd64.deb) in Guest OS, then execute

    ```shell
    sudo apt install ~/Downloads/ucsf-chimerax_1.9ubuntu22.04_amd64.deb
    ```

2. (GUEST) Install toolshed of ChimeraX-states:

    ```shell
    wget https://github.com/ShiinaHiiragi/chimerax-states/archive/refs/tags/0.5.zip -P /home/user/Downloads
    unzip /home/user/Downloads/0.5.zip -d /home/user/Downloads
    chimerax --nogui --exit --cmd "devel install /home/user/Downloads/chimerax-states-0.5 exit true"
    ```

### Kalgebra

1. (GUEST) Download `aqt` and `QT 6.5.0`:

    ```shell
    pip install aqtinstall
    echo "export PATH=\$PATH:/home/user/.local/bin" >> /home/user/.bashrc
    source /home/user/.bashrc
    aqt install-qt linux desktop 6.5.0 gcc_64 -m all -O /home/user
    ```

2. (GUEST) Download `kalgebra-kai.deb` and install it:

    ```shell
    wget https://github.com/ShiinaHiiragi/kalgebra/releases/download/1.0/kalgebra-kai.deb -P /home/user/Downloads
    sudo dpkg -i /home/user/Downloads/kalgebra-kai.deb
    LD_LIBRARY_PATH=/home/user/6.5.0/gcc_64/lib /app/bin/kalgebra
    ```

### Celestia

1. (GUEST) Configure `QT 6.5.0` mentioned above

2. (GUEST) Download `celestia-kai.deb` and install it:

    ```shell
    wget https://github.com/ShiinaHiiragi/Celestia/releases/download/0.1/celestia-kai.deb -P /home/user/Downloads
    sudo apt install /home/user/Downloads/celestia-kai.deb
    LD_LIBRARY_PATH=/home/user/6.5.0/gcc_64/lib /app/bin/celestia-qt6
    ```

### Grass GIS

1. (GUEST) Download Grass v8.4

    ```shell
    sudo add-apt-repository ppa:ubuntugis/ubuntugis-unstable
    sudo apt update
    sudo apt install grass=8.4.1-1~jammy1
    ```

2. (GUEST) Download the repo and replace raw scripts

    ```shell
    git clone https://github.com/ShiinaHiiragi/grass-gui
    sudo rm -r /usr/lib/grass84/gui/wxpython
    sudo mv ./grass-gui /usr/lib/grass84/gui/wxpython
    gnome-terminal -- /bin/bash -ic "FLASK_PORT=8000 grass --gui"
    ```

3. (GUEST) Open Grass and download `Piemonte, Italy dataset` and `Natural Earth Dataset in WGS84` manually.

4. (GUEST) Open Grass and load `natural_earth_dataset/countries@PERMANENT`, randomly add two points (one in the Mediterranean Sea) and modify `D-04.json`.

5. (GUEST) Clear GIS lock files

    ```shell
    rm -rf /home/user/grassdata/*/*/.gislock
    ```

### TeXstudio

1. (GUEST) Download TeXstudio

    ```shell
    sudo add-apt-repository ppa:sunderme/texstudio
    sudo apt update
    sudo apt install texstudio
    ```

2. (GUEST) Download MiKTeX

    ```shell
    sudo apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys D6BC243565B2087BC3F897C9277A7293F59E4889
    echo "deb http://miktex.org/download/ubuntu jammy universe" | sudo tee /etc/apt/sources.list.d/miktex.list
    sudo apt update
    sudo apt install miktex=23.12-jammy1
    miktexsetup finish
    sudo apt install texlive-fonts-extra texlive-science
    ```

    and goto `miktex-console` to allow auto installation of missing packages.

3. (GUEST) Make sure your templates can be compiled successfully

    ```shell
    pdflatex main.tex
    bibtex main
    pdflatex main.tex
    pdflatex main.tex
    ```

    and so does in TeXstuio

4. (GUEST) Add documents/figures needed by tasks

### Lean 4

1. (GUEST) Install Visual Studio Code and its extension for Lean 4

2. (GUEST) Install `elan` and `lean`

    ```shell
    sudo apt install curl
    curl https://elan.lean-lang.org/elan-init.sh -sSf | sh
    elan default leanprover/lean4:v4.14.0
    elan install leanprover/lean4:v4.14.0
    printf "export PATH=/home/user/.elan/bin:\$PATH" >> ~/.bashrc
    lake new sci
    ```

    add prefix of `HTTP_PROXY=... HTTPS_PROXY=...` if `elan install` fail to resolve `github.com`

3. Add mathlib config in `lakefile.toml`

    ```toml
    [[require]]
    name = "mathlib"
    scope = "leanprover-community"
    rev = "v4.14.0"
    ```

    and download dependencies:

    ```shell
    lake update
    lake exe cache get
    lake build
    ```

## Postprocess

1. (HOST) Move server files into guest OS:

    ```shell
    vmrun -T ws -gu user -gp password runProgramInGuest /app/VM/Ubuntu.vmx /usr/bin/bash -c "mkdir /home/user/server"
    vmrun -T ws -gu user -gp password runProgramInGuest /app/VM/Ubuntu.vmx /usr/bin/bash -c "mkdir -p /home/user/.config/systemd/user"
    vmrun -T ws -gu user -gp password CopyFileFromHostToGuest /app/VM/Ubuntu.vmx vm_config/server.py /home/user/server/main.py
    vmrun -T ws -gu user -gp password CopyFileFromHostToGuest /app/VM/Ubuntu.vmx vm_config/reset.sh /home/user/server/reset.sh
    vmrun -T ws -gu user -gp password CopyFileFromHostToGuest /app/VM/Ubuntu.vmx vm_config/pyxcursor.py /home/user/server/pyxcursor.py
    vmrun -T ws -gu user -gp password CopyFileFromHostToGuest /app/VM/Ubuntu.vmx vm_config/service.conf /home/user/.config/systemd/user/osworld.service
    ```

2. (GUEST) Start daemon process:

    ```shell
    chmod +x /home/user/server/reset.sh
    pip install python-xlib lxml pyautogui Flask numpy
    sudo apt install python3-tk python3-dev ffmpeg gnome-screenshot
    gsettings set org.gnome.desktop.interface toolkit-accessibility true

    systemctl --user daemon-reload
    systemctl --user enable osworld.service
    systemctl --user restart osworld.service
    ```

3. (HOST) Attach a `__VERSION__` file under VM directory:

    ```shell
    echo "0.1" >> /app/VM/__VERSION__
    ```

4. (HOST) Compress vmware files:

    ```shell
    cd /app/VM; zip -r ../Ubuntu-x86.zip *; cd -
    ```

## References
