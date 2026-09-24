"""The startup diagnostics around the setuid bwrap copy.

Sunshine needs CAP_SYS_ADMIN for KMS capture, which it only gets through a
setuid-root bwrap. chmod succeeding does not mean the bit took effect: a
filesystem may not store it, and on a nosuid mount it is stored but ignored at
exec. Sunshine then dies without a usable error - no DRM handle, no encoder -
so the plugin has to say so itself, and the log it writes is what a bug report
gets diagnosed from.

A) _findMountEntry - longest matching mount point, escaped paths, bad input
B) _verifySetuidBit - the bit, the mount, and what is logged when either fails
C) _readOsRelease / _readFirstLine - the environment header of every log
D) logEnvironment - the nosuid verdict and the missing-tool check

The scripted mount tables below are invented, deliberately: what a given
machine happens to have mounted is not the subject. Two things are not
invented - one test reads the kernel's own /proc/self/mounts to check the
format the parser is written against, and DECK_MOUNTS / DECK_OS_RELEASE are
verbatim from a Steam Deck, because "is the setuid bit usable where the copy
goes" is a question about that machine and no other.
"""
import os
import shutil
import stat

import pytest

import sunshine as sunshine_module
from sunshine import SunshineController


@pytest.fixture
def make_controller(bare_controller, tmp_path):
    """A controller with an optional scripted /proc/self/mounts."""
    counter = [0]

    def _make(mounts=None, **attributes):
        controller = bare_controller(**attributes)
        if mounts is not None:
            counter[0] += 1
            path = tmp_path / f"mounts-{counter[0]}"
            path.write_text(mounts)
            controller.MountsPath = str(path)
        return controller

    return _make


# --- the reference machine ----------------------------------------------------
# Verbatim from a Steam Deck (SteamOS 3.8.16, build 20260716.1). Invented mount
# tables are fine for the parser's edge cases, but only the real one answers
# the question the whole section exists for: does the filesystem that will host
# the setuid bwrap copy allow setuid at all. The awkward parts are the point -
# eleven mounts from one device, several mount points of equal length, autofs
# triggers, and a mount point that appears twice.

DECK_MOUNTS = """proc /proc proc rw,nosuid,nodev,noexec,relatime 0 0
sys /sys sysfs rw,nosuid,nodev,noexec,relatime 0 0
dev /dev devtmpfs rw,nosuid,relatime,size=7566112k,nr_inodes=1891528,mode=755,inode64 0 0
run /run tmpfs rw,nosuid,nodev,relatime,mode=755,inode64 0 0
efivarfs /sys/firmware/efi/efivars efivarfs rw,nosuid,nodev,noexec,relatime 0 0
/dev/nvme0n1p4 / btrfs rw,relatime,ssd,discard=async,space_cache=v2,subvolid=5,subvol=/ 0 0
/dev/nvme0n1p6 /var ext4 rw,relatime 0 0
overlay /etc overlay rw,relatime,lowerdir=/new_root/etc,upperdir=/new_root/var/lib/overlays/etc/upper,workdir=/new_root/var/lib/overlays/etc/work 0 0
securityfs /sys/kernel/security securityfs rw,nosuid,nodev,noexec,relatime 0 0
tmpfs /dev/shm tmpfs rw,nosuid,nodev,inode64 0 0
devpts /dev/pts devpts rw,nosuid,noexec,relatime,gid=5,mode=620,ptmxmode=000 0 0
cgroup2 /sys/fs/cgroup cgroup2 rw,nosuid,nodev,noexec,relatime,nsdelegate,memory_recursiveprot 0 0
none /sys/fs/pstore pstore rw,nosuid,nodev,noexec,relatime 0 0
bpf /sys/fs/bpf bpf rw,nosuid,nodev,noexec,relatime,mode=700 0 0
systemd-1 /proc/sys/fs/binfmt_misc autofs rw,relatime,fd=41,pgrp=1,timeout=0,minproto=5,maxproto=5,direct,pipe_ino=7617 0 0
mqueue /dev/mqueue mqueue rw,nosuid,nodev,noexec,relatime 0 0
debugfs /sys/kernel/debug debugfs rw,nosuid,nodev,noexec,relatime 0 0
hugetlbfs /dev/hugepages hugetlbfs rw,nosuid,nodev,relatime,pagesize=2M 0 0
tracefs /sys/kernel/tracing tracefs rw,nosuid,nodev,noexec,relatime 0 0
tmpfs /run/credentials/systemd-journald.service tmpfs ro,nosuid,nodev,noexec,relatime,nosymfollow,size=1024k,nr_inodes=1024,mode=700,inode64,noswap 0 0
fusectl /sys/fs/fuse/connections fusectl rw,nosuid,nodev,noexec,relatime 0 0
configfs /sys/kernel/config configfs rw,nosuid,nodev,noexec,relatime 0 0
tmpfs /run/credentials/systemd-resolved.service tmpfs ro,nosuid,nodev,noexec,relatime,nosymfollow,size=1024k,nr_inodes=1024,mode=700,inode64,noswap 0 0
systemd-1 /efi autofs rw,relatime,fd=63,pgrp=1,timeout=60,minproto=5,maxproto=5,direct,pipe_ino=7933 0 0
systemd-1 /esp autofs rw,relatime,fd=68,pgrp=1,timeout=60,minproto=5,maxproto=5,direct,pipe_ino=7939 0 0
/dev/nvme0n1p8 /home ext4 rw,relatime 0 0
/dev/nvme0n1p8 /nix ext4 rw,relatime 0 0
/dev/nvme0n1p8 /opt ext4 rw,relatime 0 0
/dev/nvme0n1p8 /root ext4 rw,relatime 0 0
/dev/nvme0n1p8 /srv ext4 rw,relatime 0 0
/dev/nvme0n1p8 /var/cache/pacman ext4 rw,relatime 0 0
/dev/nvme0n1p8 /var/lib/docker ext4 rw,relatime 0 0
/dev/nvme0n1p8 /var/lib/flatpak ext4 rw,relatime 0 0
/dev/nvme0n1p8 /var/lib/steamos-log-submitter ext4 rw,relatime 0 0
/dev/nvme0n1p8 /var/lib/systemd/coredump ext4 rw,relatime 0 0
/dev/nvme0n1p8 /var/log ext4 rw,relatime 0 0
/dev/nvme0n1p8 /var/tmp ext4 rw,relatime 0 0
tmpfs /tmp tmpfs rw,nosuid,nodev,nr_inodes=1048576,inode64 0 0
/dev/mmcblk0p1 /run/media/deck/a747b6ef-da9f-4cf7-8ee1-80040b921281 ext4 rw,nosuid,nodev,noatime,errors=remount-ro 0 0
tmpfs /run/user/1000 tmpfs rw,nosuid,nodev,relatime,size=1516036k,nr_inodes=379009,mode=700,uid=1000,gid=1000,inode64 0 0
binfmt_misc /proc/sys/fs/binfmt_misc binfmt_misc rw,nosuid,nodev,noexec,relatime 0 0
portal /run/user/1000/doc fuse.portal rw,nosuid,nodev,relatime,user_id=1000,group_id=1000 0 0
"""

# Verbatim from the same machine.
DECK_OS_RELEASE = """NAME="SteamOS"
PRETTY_NAME="SteamOS"
VERSION_CODENAME=holo
ID=steamos
ID_LIKE=arch
ANSI_COLOR="1;35"
HOME_URL="https://www.steampowered.com/"
DOCUMENTATION_URL="https://support.steampowered.com/"
SUPPORT_URL="https://support.steampowered.com/"
BUG_REPORT_URL="https://support.steampowered.com/"
LOGO=steamos
VARIANT_ID=steamdeck
VERSION_ID=3.8.16
BUILD_ID=20260716.1
STEAMOS_DEFAULT_UPDATE_BRANCH=stable
"""


def test_the_bwrap_copy_lands_on_a_filesystem_that_allows_setuid(make_controller):
    """The assumption the whole /var/lib location rests on, checked against the
    machine it was chosen for: /var is its own ext4 mount there, and it is not
    nosuid. If SteamOS ever mounts it nosuid, the copy has to move and this is
    the test that says so."""
    controller = make_controller(mounts=DECK_MOUNTS)

    mount_point, fstype, options = controller._findMountEntry(
        "/var/lib/decky-sunshine/bwrap")

    assert (mount_point, fstype) == ("/var", "ext4")
    assert "nosuid" not in options.split(",")


def test_the_deepest_mount_is_found_among_forty_others(make_controller):
    """/var/log, /var/tmp and nine more are mounts of their own from the same
    device, and /efi, /esp, /nix, /opt and /srv are all four characters long -
    a depth comparison that went by anything but the mount point would pick
    one of those."""
    controller = make_controller(mounts=DECK_MOUNTS)

    assert controller._findMountEntry("/var/log/x")[0] == "/var/log"
    assert controller._findMountEntry("/var/spool/x")[0] == "/var"
    assert controller._findMountEntry("/home/deck/x")[0] == "/home"



def test_of_two_mounts_on_the_same_point_the_later_one_counts(make_controller):
    """The Deck stacks binfmt_misc on top of an autofs trigger at the same
    mount point, and /proc/self/mounts lists them in mount order - so the
    later line is the one that is actually there. The two disagree on the
    very thing this lookup exists for: the autofs line is not nosuid, the
    binfmt_misc line on top of it is."""
    controller = make_controller(mounts=DECK_MOUNTS)

    assert controller._findMountEntry("/proc/sys/fs/binfmt_misc/status") == \
        ("/proc/sys/fs/binfmt_misc", "binfmt_misc", "rw,nosuid,nodev,noexec,relatime")

def test_the_deck_puts_tmp_on_a_nosuid_mount(make_controller):
    """Which is why the copy is not there any more: the legacy location was
    inside the plugin runtime directory, and every /tmp-shaped fallback has the
    same problem. A setuid binary there is stored and ignored."""
    controller = make_controller(mounts=DECK_MOUNTS)

    assert "nosuid" in controller._findMountEntry("/tmp/x")[2].split(",")


def test_the_real_os_release_parses_into_its_values(make_controller, tmp_path):
    """Quoted and unquoted values in the same file, a value with a semicolon
    in it, and URLs - the format is looser than it looks, and this is the one
    the plugin actually meets."""
    path = tmp_path / "os-release"
    path.write_text(DECK_OS_RELEASE)

    entries = make_controller(OsReleasePath=str(path))._readOsRelease()

    assert entries["ID"] == "steamos"
    assert entries["PRETTY_NAME"] == "SteamOS", "and not 'SteamOS 3.8.16'"
    assert entries["ANSI_COLOR"] == "1;35"
    assert entries["HOME_URL"] == "https://www.steampowered.com/"
    assert entries["BUILD_ID"] == "20260716.1"


def mounts_for(directory, options="rw,relatime"):
    """A /proc/self/mounts in which `directory` is its own mount."""
    return (f"/dev/root / ext4 rw,relatime 0 0\n"
            f"proc /proc proc rw,nosuid,nodev,noexec 0 0\n"
            f"tmpfs {directory} tmpfs {options} 0 0\n")


# --- A) _findMountEntry -------------------------------------------------------

def test_the_real_proc_self_mounts_has_the_shape_the_parser_expects(make_controller):
    """The one test that reads the kernel's own file: a parser checked only
    against invented lines proves nothing about the format it has to read.
    Everything below scripts the file, because what a given machine happens to
    have mounted is not the subject - and the machine that matters, the Deck,
    is not the one running this."""
    entry = make_controller()._findMountEntry("/proc/self/mounts")

    assert entry is not None
    mount_point, fstype, options = entry
    assert (mount_point, fstype) == ("/proc", "proc")
    assert "nosuid" in options.split(","), "the kernel has mounted /proc nosuid for decades"


def test_a_path_that_does_not_exist_still_resolves_to_a_mount(make_controller):
    """The bwrap directory does not exist yet on a fresh install, and the mount
    that will host it still has to be found."""
    controller = make_controller(mounts="/dev/root / ext4 rw,relatime 0 0\n")

    assert controller._findMountEntry("/var/lib/decky-sunshine/bwrap") == \
        ("/", "ext4", "rw,relatime")


def test_octal_escaped_mount_points_are_decoded(make_controller):
    controller = make_controller(mounts="/dev/root / ext4 rw,relatime 0 0\n"
                                        "tmpfs /mnt/my\\040disk tmpfs rw,nosuid 0 0\n")

    entry = controller._findMountEntry("/mnt/my disk/file")

    assert entry is not None
    assert entry[0] == "/mnt/my disk"


# The root line carries a filesystem type longer than the deepest mount point,
# so only a comparison of the mount points themselves gives the right answer:
# with ext4 and tmpfs the lengths happen to order the same way as the paths.
DEEP = "tmpfs /var/lib tmpfs rw,nosuid 0 0\n"
SHALLOW = "tmpfs /var tmpfs rw 0 0\n"
ROOT = "/dev/root / fuseblk-with-a-very-long-name rw 0 0\n"


@pytest.mark.parametrize("mounts, why", [
    (ROOT + SHALLOW + DEEP, "deepest last"),
    (DEEP + SHALLOW + ROOT, "deepest first"),
])
def test_the_deepest_matching_mount_wins_whatever_the_order(make_controller, mounts, why):
    """/proc/self/mounts is in mount order, not depth order, so the deepest
    match may come anywhere - and a shallower one must not replace it. That
    would read the options of the wrong filesystem and could call a perfectly
    good target nosuid, or miss that it is."""
    controller = make_controller(mounts=mounts)

    assert controller._findMountEntry("/var/lib/decky-sunshine/bwrap") == \
        ("/var/lib", "tmpfs", "rw,nosuid"), why


def test_a_mount_point_is_not_matched_as_a_mere_string_prefix(make_controller):
    """/varnish is not under /var."""
    controller = make_controller(mounts="/dev/root / ext4 rw 0 0\ntmpfs /var tmpfs rw 0 0\n")

    assert controller._findMountEntry("/varnish/file")[0] == "/"


def test_malformed_lines_are_skipped_rather_than_fatal(make_controller):
    controller = make_controller(mounts="garbage\n/dev/root / ext4 rw 0 0\nalso bad\n")

    assert controller._findMountEntry("/x")[0] == "/"


def test_an_unreadable_mounts_file_yields_none(make_controller, tmp_path):
    controller = make_controller(MountsPath=str(tmp_path / "does-not-exist"))

    assert controller._findMountEntry("/x") is None


# --- B) _verifySetuidBit ------------------------------------------------------
# The bit itself is real - only the mount it appears to sit on is scripted.

@pytest.fixture
def plain_binary(tmp_path):
    """A real executable, without the setuid bit."""
    target = tmp_path / "bwrap"
    shutil.copy(shutil.which("true"), target)
    return target


@pytest.fixture
def setuid_binary(plain_binary):
    """The same, with the setuid bit actually stored by the filesystem.

    Skipped where it is not: tmpfs and several overlay setups accept the chmod
    and drop the bit, and a test that silently passed on those would be telling
    us nothing about the case it exists for.
    """
    plain_binary.chmod(plain_binary.stat().st_mode | stat.S_ISUID)
    if not plain_binary.stat().st_mode & stat.S_ISUID:
        pytest.skip(f"the filesystem hosting {plain_binary.parent} does not store the setuid bit")
    return plain_binary


def test_a_file_without_the_setuid_bit_is_rejected(make_controller, plain_binary, logger):
    controller = make_controller(mounts=mounts_for(plain_binary.parent, "rw,relatime"))

    assert controller._verifySetuidBit(str(plain_binary)) is False
    assert any("did not persist" in line for line in logger.errors)
    # The mount and its options, not just the path: the file path already
    # contains its parent directory, so a substring check on that passes even
    # with the hint gone.
    assert any(f"(mount {plain_binary.parent}, options: rw,relatime)" in line
               for line in logger.errors), \
        "a bug report is diagnosed from this line"


def test_without_mount_information_the_message_carries_no_hint(make_controller,
                                                               plain_binary, logger):
    """The mount lookup failed, so there is nothing to say about it - and an
    empty pair of brackets in the middle of the sentence reads like a bug."""
    controller = make_controller(MountsPath="/nonexistent/mounts")

    assert controller._verifySetuidBit(str(plain_binary)) is False
    assert (f"The setuid bit on {plain_binary} did not persist - without it Sunshine "
            "cannot access the DRM framebuffer and will exit silently. The target "
            "directory may need to move to a filesystem supporting setuid.") in logger.errors


def test_a_setuid_file_on_a_suid_capable_mount_is_accepted(
        make_controller, setuid_binary, logger):
    controller = make_controller(mounts=mounts_for(setuid_binary.parent))

    assert controller._verifySetuidBit(str(setuid_binary)) is True
    assert logger.errors == [], "acceptance is silent"


def test_a_setuid_file_on_a_nosuid_mount_is_rejected(make_controller, setuid_binary, logger):
    """The case that is hardest to diagnose: the bit is set, ls -l shows it,
    and the kernel ignores it anyway."""
    controller = make_controller(mounts=mounts_for(setuid_binary.parent, "rw,nosuid,relatime"))

    assert controller._verifySetuidBit(str(setuid_binary)) is False
    assert any("mounted nosuid" in line for line in logger.errors)
    assert not any("did not persist" in line for line in logger.errors), \
        "saying 'bit missing' here would send the reader looking in the wrong place"


def test_a_mounts_line_with_too_few_fields_is_skipped(make_controller, tmp_path):
    """The parser needs four: mount point, fstype and options come from the
    second, third and fourth. A short line is not one it can read, and reading
    it half-way would report an fstype that is really a mount point."""
    controller = make_controller(
        mounts=f"/dev/root / ext4\ntmpfs {tmp_path} tmpfs rw,relatime 0 0\n")

    assert controller._findMountEntry(str(tmp_path)) == (str(tmp_path), "tmpfs", "rw,relatime")


def test_a_four_field_line_is_still_readable(make_controller, tmp_path):
    """The other side of the same bound: /proc/self/mounts always has six
    fields, but the two we do not read are the ones a shorter format would
    drop first."""
    controller = make_controller(mounts=f"tmpfs {tmp_path} tmpfs rw,relatime\n")

    assert controller._findMountEntry(str(tmp_path)) == (str(tmp_path), "tmpfs", "rw,relatime")


def test_an_option_merely_containing_nosuid_is_not_nosuid(make_controller, setuid_binary):
    controller = make_controller(mounts=mounts_for(setuid_binary.parent, "rw,nosuiddir,relatime"))

    assert controller._verifySetuidBit(str(setuid_binary)) is True


def test_a_missing_file_is_rejected_rather_than_raising(make_controller, tmp_path, logger):
    controller = make_controller(mounts=mounts_for(tmp_path))
    absent = tmp_path / "absent"

    assert controller._verifySetuidBit(str(absent)) is False
    assert logger.raised_with_traceback(
        f"An error occurred when verifying the setuid bit on {absent}")


def test_an_unknown_mount_does_not_veto_a_set_bit(make_controller, setuid_binary,
                                                  tmp_path, logger):
    """Without mount information the mode is all we have, and it has to be
    enough: refusing to start on an unreadable /proc would be worse."""
    controller = make_controller(MountsPath=str(tmp_path / "does-not-exist"))

    assert controller._verifySetuidBit(str(setuid_binary)) is True
    assert logger.raised_with_traceback(
        f"An error occurred when looking up the mount for {setuid_binary}"), \
        "it carried on, so the log is the only record that it had to guess"


# --- C) the environment header ------------------------------------------------

@pytest.fixture
def os_release(tmp_path):
    path = tmp_path / "os-release"
    path.write_text('# NAME="Not SteamOS"\n\nNAME="SteamOS"\nVERSION_ID="3.8.16"\n'
                    'BUILD_ID=20260716.1\nHOME_URL="https://example.org/?a=b"\n'
                    'MALFORMED\n')
    return path


def test_os_release_is_parsed_into_a_dict(make_controller, os_release):
    entries = make_controller(OsReleasePath=str(os_release))._readOsRelease()

    assert entries.get("NAME") == "SteamOS", "quotes are stripped, and a commented-out entry does not win"
    assert entries.get("BUILD_ID") == "20260716.1", "unquoted values survive"
    assert entries.get("HOME_URL") == "https://example.org/?a=b", "a value may contain '=' itself"
    assert not any(key.startswith("#") for key in entries), "comment lines are skipped"
    assert "MALFORMED" not in entries, "lines without '=' are skipped"


def test_an_unreadable_os_release_is_not_fatal(make_controller, tmp_path, logger):
    entries = make_controller(OsReleasePath=str(tmp_path / "absent"))._readOsRelease()

    assert entries == {}
    assert logger.raised_with_traceback(
        "An error occurred when reading /etc/os-release")


def test_read_first_line(make_controller, os_release, tmp_path):
    controller = make_controller()

    assert controller._readFirstLine(str(os_release)).startswith("#")
    assert controller._readFirstLine(str(tmp_path / "absent")) is None
    assert controller._readFirstLine(str(tmp_path)) is None, "a directory, not an exception"


# --- D) logEnvironment --------------------------------------------------------
# This is what a bug report is read from, so its verdicts matter as much as the
# facts around them.

@pytest.fixture
def log_environment(make_controller, monkeypatch, tmp_path, logger):
    """Runs logEnvironment against a scripted system."""

    def _run(mounts, missing_tools=(), bwrap_present=True, library_path=None,
             os_id="steamos", vendor="Valve", product="Jupiter", session_user="deck",
             os_release=None, docked=False, no_path=False):
        environment = {"FLATPAK_BWRAP": str(tmp_path / "bwrap"),
                       "PATH": "/usr/bin", "PULSE_SERVER": "unix:/x"}
        if library_path is not None:
            environment["LD_LIBRARY_PATH"] = library_path

        controller = make_controller(mounts=mounts, environment_variables=environment)
        # The reference machine's own values - PRETTY_NAME really is just
        # "SteamOS" there, with no version in it.
        entries = {"NAME": "SteamOS", "ID": os_id,
                   "PRETTY_NAME": "SteamOS",
                   "VERSION_ID": "3.8.16",
                   "BUILD_ID": "20260716.1"} if os_release is None else os_release
        controller._readOsRelease = lambda: entries
        dmi = {"/sys/class/dmi/id/board_vendor": vendor,
               "/sys/class/dmi/id/product_name": product}
        controller._readFirstLine = dmi.get
        if no_path:
            del environment["PATH"]
        controller._isExternalDisplayConnected = lambda: docked
        # Stubbed rather than left to the host: the real one reads /run/user and
        # the passwd database, so the verdicts below would depend on whoever
        # happens to be logged in on the machine running the tests.
        controller._getSessionUsername = lambda: session_user

        real_isfile = os.path.isfile
        searched.clear()

        def which(tool, path=None):
            # The path is recorded rather than ignored: which PATH the survey
            # searches is the difference between "the tools Sunshine will find"
            # and "the tools this process happens to see".
            searched.append(path)
            return None if tool in missing_tools else f"/usr/bin/{tool}"

        monkeypatch.setattr(sunshine_module.shutil, "which", which)
        monkeypatch.setattr(sunshine_module.os.path, "isfile",
                            lambda p: bwrap_present if p == "/usr/bin/bwrap" else real_isfile(p))
        controller.logEnvironment()
        return logger

    searched = []
    _run.searched = searched
    return _run


def test_a_healthy_environment_logs_no_error(log_environment, tmp_path):
    log = log_environment(mounts_for(tmp_path))

    assert log.errors == []
    # Which DMI attribute is read, not just that something was: swap the two
    # and every Deck reports itself as not a Valve device.
    assert any("Hardware: Valve Jupiter" in line for line in log.infos)
    assert not any("nosuid" in line for line in log.infos), \
        "the mount line must not claim nosuid when it is not"
    # These four are the whole point of the section: a bug report starts by
    # reading them, so each is pinned as the reader will see it.
    assert ("Environment: OS: SteamOS (ID=steamos, VERSION_ID=3.8.16, "
            "BUILD_ID=20260716.1)") in log.infos, \
        "PRETTY_NAME is just \"SteamOS\" on a Deck - the version has to come from elsewhere"
    assert "Environment: PULSE_SERVER: unix:/x" in log.infos
    assert "Environment: External display: not connected" in log.infos
    assert f"Environment: bwrap copy target {tmp_path}: mount {tmp_path} (tmpfs)" in log.infos


def test_a_nosuid_mount_is_called_out_as_an_error(log_environment, tmp_path):
    log = log_environment(mounts_for(tmp_path, "rw,nosuid"))

    assert any("mounted nosuid" in line for line in log.errors)
    assert f"Environment: bwrap copy target {tmp_path}: mount {tmp_path} (tmpfs, nosuid)" \
        in log.infos, "and is visible in the info line too"


def test_missing_tools_are_separated_by_how_badly_they_are_needed(log_environment, tmp_path):
    log = log_environment(mounts_for(tmp_path), missing_tools={"drm_info", "xprop"})

    assert ("Missing required tools: drm_info - Sunshine cannot be installed/started"
            in log.errors)
    assert ("Missing tools needed only for the force-composition toggle: xprop"
            in log.warnings), "composition-only tools are a warning, not an error"
    assert not any("xprop" in line for line in log.errors), \
        "and xprop alone must not read as 'Sunshine cannot start'"


@pytest.mark.parametrize("missing, said", [((), True), (("xprop",), False)])
def test_all_present_is_only_said_when_it_really_is(log_environment, tmp_path, missing, said):
    """A composition-only tool is a warning, not an error - but the summary
    line still may not call the toolchain complete."""
    log = log_environment(mounts_for(tmp_path), missing_tools=set(missing))

    assert ("Environment: Tools: all present "
            "(flatpak, cp, chown, chmod, drm_info, su, xprop)" in log.infos) is said


def test_several_missing_tools_are_listed_as_a_readable_line(log_environment, tmp_path):
    """One missing tool cannot tell a list apart from a concatenation - and
    "chmoddrm_info" in a bug report costs the reader a detour."""
    log = log_environment(mounts_for(tmp_path),
                          missing_tools={"chmod", "drm_info", "su", "xprop"})

    assert ("Missing required tools: chmod, drm_info - Sunshine cannot be "
            "installed/started") in log.errors
    assert ("Missing tools needed only for the force-composition toggle: su, xprop"
            in log.warnings)


def test_an_os_release_without_the_usual_keys_still_reads_sensibly(log_environment,
                                                                   make_controller,
                                                                   tmp_path, monkeypatch):
    """Not every distribution fills PRETTY_NAME, and the line has to stay
    readable rather than print None - it is the first thing in a bug report."""
    log = log_environment(mounts_for(tmp_path), os_release={})

    assert "Environment: OS: unknown (ID=unknown)" in log.infos
    assert ("OS is not SteamOS - this plugin makes Steam-Deck-specific assumptions "
            "that may not hold here") in log.warnings


def test_hardware_that_does_not_say_what_it_is_reads_as_unknown(log_environment,
                                                                tmp_path):
    """A virtual machine, or a board that fills no DMI strings. The line still
    has to be readable - "Hardware: None None" reads like a plugin bug."""
    log = log_environment(mounts_for(tmp_path), vendor=None, product=None)

    assert any(line.startswith("Environment: Hardware: unknown unknown, Kernel: ")
               for line in log.infos)


def test_the_tool_survey_searches_the_path_subprocesses_will_get(log_environment,
                                                                 tmp_path):
    """The same PATH the spawned tools will be given, not the plugin process's
    own - otherwise the survey reports a toolchain that is complete for
    somebody else."""
    log_environment(mounts_for(tmp_path))

    assert set(log_environment.searched) == {"/usr/bin"}, \
        "that is the PATH the fixture puts in the controller's environment"


def test_without_a_path_of_its_own_the_survey_falls_back_to_the_default(log_environment,
                                                                        tmp_path):
    """Not os.environ's PATH: the controller deliberately carries its own
    environment, and an absent entry there means the default search path."""
    log_environment(mounts_for(tmp_path), no_path=True)

    assert set(log_environment.searched) == {os.defpath}


def test_a_connected_external_display_is_named_as_such(log_environment, tmp_path):
    """The other half of the line. The override only does anything while a
    display is attached, so which of the two words is printed is the whole
    information."""
    log = log_environment(mounts_for(tmp_path), docked=True)

    assert "Environment: External display: connected" in log.infos


def test_a_missing_system_bwrap_is_an_error(log_environment, tmp_path):
    log = log_environment(mounts_for(tmp_path), bwrap_present=False)

    assert ("/usr/bin/bwrap not found - cannot create the setuid bwrap copy "
            "Sunshine needs for KMS capture") in log.errors


def test_the_library_path_is_logged_either_way(log_environment, tmp_path):
    """The loader's bundled libraries are invisible from the panel and
    only ever showed up here."""
    log = log_environment(mounts_for(tmp_path), library_path="/tmp/_MEI123")
    assert any("LD_LIBRARY_PATH: /tmp/_MEI123" in line for line in log.infos)


def test_an_unset_library_path_is_logged_as_such(log_environment, tmp_path):
    log = log_environment(mounts_for(tmp_path))

    assert any("LD_LIBRARY_PATH: <unset>" in line for line in log.infos)



def test_version_keys_a_distribution_does_not_set_are_left_out(log_environment, tmp_path):
    """A rolling release has a BUILD_ID and no VERSION_ID. Left out rather
    than printed as "unknown", which would read as a lookup that failed."""
    log = log_environment(mounts_for(tmp_path),
                          os_release={"ID": "arch", "PRETTY_NAME": "Arch Linux",
                                      "BUILD_ID": "rolling"})

    assert "Environment: OS: Arch Linux (ID=arch, BUILD_ID=rolling)" in log.infos

def test_a_steamos_deck_draws_no_warning_about_the_platform(log_environment, tmp_path):
    log = log_environment(mounts_for(tmp_path))

    assert log.warnings == []
    assert any("ID=steamos" in line for line in log.infos)


def test_another_distribution_is_flagged_without_being_refused(log_environment, tmp_path):
    """Decky also runs on Bazzite, ChimeraOS and Nobara. The assumptions this
    plugin makes may not hold there, which is worth a line in the log and
    nothing more - loading never fails over it."""
    log = log_environment(mounts_for(tmp_path), os_id="bazzite")

    assert ("OS is not SteamOS - this plugin makes Steam-Deck-specific assumptions "
            "that may not hold here") in log.warnings
    assert ("Environment: OS: SteamOS (ID=bazzite, VERSION_ID=3.8.16, "
            "BUILD_ID=20260716.1)") in log.infos
    assert log.errors == []


def test_hardware_that_is_not_a_valve_device_is_flagged(log_environment, tmp_path):
    log = log_environment(mounts_for(tmp_path), vendor="ASUSTeK COMPUTER INC.")

    assert ("Hardware is not a Valve device - display/audio detection may behave "
            "differently") in log.warnings


def test_a_missing_session_user_is_an_error(log_environment, tmp_path):
    """Both the audio discovery and the composition override write as that
    user; without one, neither can work."""
    log = log_environment(mounts_for(tmp_path), session_user=None)

    assert ("No session user found (no user \'deck\', no /run/user/<uid> with uid >= 1000) "
            "- audio discovery and the composition override will fail") in log.errors


def test_the_session_user_is_named_when_there_is_one(log_environment, tmp_path):
    log = log_environment(mounts_for(tmp_path), session_user="gamer")

    assert any("Session user: gamer" in line for line in log.infos)


def test_a_mount_that_cannot_be_determined_is_a_warning_not_an_error(log_environment,
                                                                     tmp_path):
    """Unknown is not the same as nosuid: the setuid copy may well work, and
    calling it broken would send people chasing the wrong thing."""
    log = log_environment(mounts="")

    assert any("Could not determine the mount" in line for line in log.warnings)
    assert not any("nosuid" in line for line in log.errors)


def test_a_broken_probe_never_stops_the_plugin_from_loading(make_controller, tmp_path):
    """Everything here is informational. An exception in the diagnostics would
    otherwise take down the load it is supposed to explain."""
    controller = make_controller(mounts=mounts_for(tmp_path),
                                 environment_variables={"FLATPAK_BWRAP": str(tmp_path / "bwrap"),
                                                        "PATH": "/usr/bin"})

    def explode():
        raise RuntimeError("no /etc/os-release, no anything")

    controller._readOsRelease = explode

    controller.logEnvironment()      # must not raise

    assert controller.logger.raised_with_traceback(
        "An error occurred when logging the environment")
