#!/usr/bin/env python3
"""Build a reproducible source overlay; never edits the original ShiYi app."""
import argparse
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "https://github.com/Freeyourgadget/Gadgetbridge.git"
PIN = "a0948ee1cbc2a870f91d313f8e37df5f524465f7"
PACKAGE = Path("org/aihealthy/shiyi")
DAO_UPSTREAM = "https://github.com/Freeyourgadget/greenDAO.git"
DAO_PIN = "1998d7cd2d21f662c6044f6ccf3b3a251bbad341"


def run(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True)


def replace_once(path, old, new):
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(f"Expected one anchor in {path}: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def prepare(dest):
    if dest.exists():
        raise SystemExit("Destination already exists; choose a new directory (never overwrites).")
    dest.mkdir(parents=True)
    run("git", "init", str(dest))
    run("git", "fetch", "--depth=1", UPSTREAM, PIN, cwd=dest)
    run("git", "checkout", "--detach", "FETCH_HEAD", cwd=dest)
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=dest, text=True).strip()
    if actual != PIN:
        raise RuntimeError("Unexpected upstream commit")
    run("git", "submodule", "update", "--init", "--recursive", cwd=dest)

    # The historical JitPack artifact is no longer available. Compile exactly
    # the same generator sources and templates, not a different ORM version.
    dao = dest / "third_party/greendao"
    dao.mkdir(parents=True)
    run("git", "init", str(dao))
    run("git", "fetch", "--depth=1", DAO_UPSTREAM, DAO_PIN, cwd=dao)
    run("git", "checkout", "--detach", "FETCH_HEAD", cwd=dao)
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=dao, text=True).strip() != DAO_PIN:
        raise RuntimeError("Unexpected greenDAO commit")
    generator = dest / "GBDaoGenerator/build.gradle"
    replace_once(generator,
                 "implementation 'com.github.Freeyourgadget:greendao:1998d7cd2d21f662c6044f6ccf3b3a251bbad341'",
                 "implementation 'org.freemarker:freemarker:2.3.23'")
    replace_once(generator, "srcDir 'src'",
                 "srcDir 'src'\n            srcDir '../third_party/greendao/DaoGenerator/src'")
    with generator.open("a", encoding="utf-8") as f:
        f.write("\nsourceSets.main.resources.srcDir '../third_party/greendao/DaoGenerator/src-template'\n")

    project = dest / "build.gradle"
    replace_once(project, "classpath 'com.android.tools.build:gradle:8.6.1'",
                 "classpath 'com.android.tools.build:gradle:8.6.1'\n"
                 "        classpath 'org.jetbrains.kotlin:kotlin-gradle-plugin:2.0.21'\n"
                 "        classpath 'org.jetbrains.kotlin:compose-compiler-gradle-plugin:2.0.21'")
    gradle = dest / "app/build.gradle"
    replace_once(gradle, 'apply plugin: "com.android.application"',
                 'apply plugin: "com.android.application"\n'
                 "apply plugin: 'org.jetbrains.kotlin.android'\n"
                 "apply plugin: 'org.jetbrains.kotlin.plugin.compose'")
    replace_once(gradle, 'applicationId "nodomain.freeyourgadget.gadgetbridge"',
                 'applicationId "org.aihealthy.shiyi.embedded"')
    replace_once(gradle, 'versionName "0.83.0"', 'versionName "0.83.0-shiyi-wearable-data"')
    replace_once(gradle, "versionCode 235", "versionCode 241")
    replace_once(gradle, "compileSdk 34", "compileSdk 35")
    replace_once(gradle, "minSdkVersion 21", "minSdkVersion 26")
    replace_once(gradle, "        aidl true", "        compose true\n        aidl true")
    replace_once(gradle, "    coreLibraryDesugaring 'com.android.tools:desugar_jdk_libs:2.1.3'",
                 "    coreLibraryDesugaring 'com.android.tools:desugar_jdk_libs:2.1.3'\n"
                 "    implementation platform('androidx.compose:compose-bom:2024.10.01')\n"
                 "    implementation 'androidx.activity:activity-compose:1.9.3'\n"
                 "    implementation 'androidx.compose.ui:ui'\n"
                 "    implementation 'androidx.compose.material3:material3'\n"
                 "    implementation 'androidx.compose.foundation:foundation'\n"
                 "    implementation 'org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0'")
    with gradle.open("a", encoding="utf-8") as f:
        f.write("\nandroid { kotlinOptions { jvmTarget = '1.8' } }\n"
                "tasks.withType(org.jetbrains.kotlin.gradle.tasks.KotlinCompile).configureEach {\n"
                "    dependsOn(\":GBDaoGenerator:genSources\")\n}\n")

    manifest = dest / "app/src/main/AndroidManifest.xml"
    replace_once(manifest, "    <!-- Used for Bluetooth access -->",
                 '    <uses-permission android:name="android.permission.INTERNET" />\n'
                 "    <!-- Used for Bluetooth access -->")
    replace_once(manifest, 'android:label="@string/app_name"\n        android:roundIcon',
                 'android:label="时宜"\n        android:roundIcon')
    replace_once(manifest, 'android:icon="@mipmap/ic_launcher"',
                 'android:icon="@mipmap/ic_shiyi_launcher"')
    replace_once(manifest, 'android:roundIcon="@mipmap/ic_launcher_round"',
                 'android:roundIcon="@mipmap/ic_shiyi_launcher"')
    replace_once(manifest, 'android:allowBackup="false"',
                 'android:allowBackup="false" android:usesCleartextTraffic="false"')
    replace_once(manifest, '                <category android:name="android.intent.category.LAUNCHER" />',
                 '                <!-- Device center remains available inside ShiYi. -->')
    replace_once(manifest, '        <activity\n            android:name=".activities.ControlCenterv2"',
                 '        <activity android:name="org.aihealthy.shiyi.MainActivity"\n'
                 '            android:exported="true" android:label="时宜"\n'
                 '            android:theme="@android:style/Theme.Material.Light.NoActionBar">\n'
                 '            <intent-filter>\n'
                 '                <action android:name="android.intent.action.MAIN" />\n'
                 '                <category android:name="android.intent.category.LAUNCHER" />\n'
                 '            </intent-filter>\n'
                 '        </activity>\n'
                 '        <activity\n            android:name=".activities.ControlCenterv2"')

    icon_rel = Path("res/mipmap-xxxhdpi/ic_shiyi_launcher.webp")
    icon_source = ROOT / "apps/android/app/src/main" / icon_rel
    icon_target = dest / "app/src/main" / icon_rel
    icon_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(icon_source, icon_target)

    wallpaper = Path("res/drawable-nodpi/shiyi_home_landscape.webp")
    wallpaper_target = dest / "app/src/main" / wallpaper
    wallpaper_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "apps/android/app/src/main" / wallpaper, wallpaper_target)

    # Android advertisements can contain a name before BluetoothDevice caches it.
    candidate = dest / "app/src/main/java/nodomain/freeyourgadget/gadgetbridge/impl/GBDeviceCandidate.java"
    replace_once(candidate, "    public boolean isNameKnown() {",
                 "    public void setShiYiAdvertisedName(String name) {\n"
                 "        if (name != null && !name.isEmpty()) deviceName = name;\n"
                 "    }\n\n"
                 "    public boolean isNameKnown() {")

    source = ROOT / "apps/android/app/src/main/java" / PACKAGE
    target = dest / "app/src/main/java" / PACKAGE
    for name in ("MainActivity.kt", "ShiYiHome.kt", "integration/wearable/WearableReader.kt",
                 "core/network/HealthApiClient.kt"):
        out = target / name
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, out)
    replace_once(target / "MainActivity.kt",
                 "import org.aihealthy.shiyi.integration.healthconnect.WearablePanel",
                 "import org.aihealthy.shiyi.integration.embedded.WearablePanel")
    replace_once(target / "MainActivity.kt",
                 "import org.aihealthy.shiyi.integration.embedded.WearablePanel",
                 "import org.aihealthy.shiyi.integration.embedded.WearablePanel\n"
                 "import org.aihealthy.shiyi.integration.embedded.HealthDashboardHost\n"
                 "import org.aihealthy.shiyi.integration.embedded.HealthOverviewCard")
    replace_once(target / "MainActivity.kt", "setContent { ShiYiApp() }",
                 "setContent { HealthDashboardHost(this) { ShiYiApp() } }")
    replace_once(target / "MainActivity.kt",
                 '5 -> item { WearablePanel() }',
                 '5 -> {\n'
                 '                        item { HealthOverviewCard(onManage = { tab = 3 }) }\n'
                 '                        item { WearablePanel() }\n'
                 '                    }')
    replace_once(target / "ShiYiHome.kt", "import java.time.LocalDate",
                 "import java.time.LocalDate\nimport nodomain.freeyourgadget.gadgetbridge.R")
    shutil.copytree(source / "companion", target / "companion")
    shutil.copytree(ROOT / "apps/gadgetbridge-embedded/src", target / "integration/embedded")
    test_target = dest / "app/src/test/java" / PACKAGE / "integration/embedded"
    test_target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "apps/gadgetbridge-embedded/tests/DailyHealthAggregatorTest.kt",
                 test_target / "DailyHealthAggregatorTest.kt")
    # The upstream source, its license, and the complete overlay must accompany distribution.
    print(f"Prepared {dest}; build with ./gradlew :app:assembleMainlineDebug")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=Path, required=True, help="New source checkout directory")
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    dest = args.dest.expanduser().resolve()
    prepare(dest)
    if args.build:
        run("bash", "./gradlew", ":app:assembleMainlineDebug", "--no-daemon", cwd=dest)
