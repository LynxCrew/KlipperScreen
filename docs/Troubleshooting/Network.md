# Network

The network panel relies on Network-Manager for its operation.

!!! info "Note for Forks"
    The network panel's behavior and dependencies may differ. Please refer to your specific fork documentation or support resources for instructions tailored to your setup.

Check if network-manager is installed:

```bash
dpkg -s network-manager
```

if the response is the following:

```sh
dpkg-query: the package 'network-manager' is not installed
```

if the response is the following:

```sh
Package: network-manager
Status: install ok installed
```

this line may appear in KlipperScreen.log:
!!! abstract "Log"
    ```sh
    [wifi_nm.py:rescan()] [...] NetworkManager.wifi.scan request failed: not authorized
    ```

if version of KlipperScreen installed was previous than v0.3.9, then re-run the installer and reboot


??? Alternative workaround for network-manager

    in order to fix this polkit needs to be configured or disabled:

    here is how to disable polkit for network-manager:

    ```sh
    mkdir -p /etc/NetworkManager/conf.d
    sudo nano /etc/NetworkManager/conf.d/any-user.conf
    ```

    in the editor paste this:

    ```ini
    [main]
    auth-polkit=false
    ```

    Then restart the service (or reboot):

    ```sh
    systemctl restart NetworkManager.service
    systemctl restart KlipperScreen.service
    ```
