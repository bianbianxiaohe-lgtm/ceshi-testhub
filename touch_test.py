import os, sys, subprocess, traceback
sys.path.insert(0, '/app')
os.chdir('/app')
os.environ['DJANGO_SETTINGS_MODULE'] = 'backend.settings'
import django; django.setup()

from apps.ui_automation.airtest_engine import AirtestRecordingEngine

e = AirtestRecordingEngine(serial='20a1ae2d', app_package='com.android.settings')
e.connect()

with open('/tmp/touch_debug2.txt', 'w') as f:
    try:
        adb = e._resolve_adb()
        f.write('ADB=' + str(adb) + '\n')
        base = [adb, '-s', e.serial, '-H', e.adb_host, '-P', str(e.adb_port), 'shell']
        r = subprocess.run(base + ['ls', '/dev/input/'], capture_output=True, text=True, timeout=5)
        f.write('LS_RC=' + str(r.returncode) + ' STDOUT=[' + r.stdout + '] STDERR=[' + r.stderr + ']\n')
        events = []
        for line in (r.stdout or '').splitlines():
            l = line.strip()
            if l.startswith('event') and l[5:].isdigit():
                events.append('/dev/input/' + l)
        f.write('EVENTS=' + str(events) + '\n')

        for dev in events:
            pr = subprocess.run(base + ['getevent', '-pl', dev],
                               capture_output=True, text=True, timeout=3)
            out = (pr.stdout or '') + (pr.stderr or '')
            has_mt = 'ABS_MT' in out
            f.write(dev + ': HAS_MT=' + str(has_mt) + '\n')

        # Now call actual method
        result = e._find_touch_device()
        f.write('RESULT=' + str(result) + '\n')
    except Exception as ex:
        f.write('EXCEPTION: ' + str(ex) + '\n' + traceback.format_exc() + '\n')
        result = None

e.disconnect()
