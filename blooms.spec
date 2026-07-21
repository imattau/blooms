%define name blooms-in-gnome
%define version 0.1.0
%define release 1

Name:           %{name}
Version:        %{version}
Release:        %{release}%{?dist}
Summary:        Nostr Blossom FUSE mount with tray icon

License:        LGPL-3.0-or-later
URL:            https://github.com/anomalyco/blooms
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  python3-setuptools
BuildRequires:  python3-pip

Requires:       python3
Requires:       python3-gobject
Requires:       python3-requests
Requires:       python3-cryptography
Requires:       fuse
Requires:       fuse-libs
Requires:       fuse3
Requires:       fuse3-libs

%description
Mount your Nostr Blossom server as a FUSE directory with a
system tray icon. Encrypts files with NIP-44 (ECDH + ChaCha20-Poly1305).
Works in any file manager.

%prep
%setup -q -n %{name}-%{version}

%build
%py3_build

%install
%py3_install

# Install systemd user service
install -D -m 644 blooms.service \
    %{buildroot}%{_userunitdir}/blooms.service

# Install desktop autostart
install -D -m 644 blooms-in-gnome.desktop \
    %{buildroot}%{_sysconfdir}/xdg/autostart/blooms-in-gnome.desktop

# Install mount helper
install -D -m 755 blooms_in_gnome/mount.sh \
    %{buildroot}%{_bindir}/blooms-mount

# Install locale files
for po_dir in locale/*/LC_MESSAGES; do
    lang=$(basename $(dirname $po_dir))
    install -D -m 644 $po_dir/blooms-in-gnome.mo \
        %{buildroot}%{_datadir}/locale/$lang/LC_MESSAGES/blooms-in-gnome.mo
done

%files
%{python3_sitelib}/blooms_in_gnome/
%{_bindir}/blooms-mount
%{_userunitdir}/blooms.service
%{_sysconfdir}/xdg/autostart/blooms-in-gnome.desktop
%{_datadir}/locale/*/LC_MESSAGES/blooms-in-gnome.mo

%changelog
* Wed Jul 22 2026 Blooms in Gnome contributors
- Initial package
