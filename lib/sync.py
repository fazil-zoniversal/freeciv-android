import threading
import time
import os
import traceback
import functools
import features

import civsync
import ui
import uidialog
import save

try:
    import lzma
except:
    import pyjni
    
    class lzma:
        def decompress(self, data):
            return pyjni.encode_or_decode_xz(1, data)
        
        def compress(self, data):
            return pyjni.encode_or_decode_xz(0, data)
    lzma = lzma()

def apply_host_change(host):
    print 'using civsync host', host
    civsync.HOST = host

features.set_applier('civsync.host', apply_host_change, default=civsync.HOST)

def apply_user_agent_change(ua):
    civsync.USER_AGENT = ua

features.set_applier('civsync.ua', apply_user_agent_change)
features.set('civsync.ua', 'CivSyncAndroid/1002')
features.add_feature('civsync.enable', False, type=bool)

session = None

def show_load():
    request(show_list, 'list')

def show_list(entries):
    panel = ui.LinearLayoutWidget()
    panel.add(ui.Label('Saves from %s' % civsync.HOST))
    for entry in entries:
        panel.add(ui.Button('%s - %dkB' % (entry.name, entry.size/1024), functools.partial(download_sync, entry.sha1)))
    if not entries:
        panel.add(ui.Label('You have not synced any saves...'))
        panel.add(ui.Label('Install Freeciv Sync for Desktop'))
        panel.add(ui.Label('from %s' % civsync.HOST))
    panel.add(ui.Button('Logout', logout))
    ui.set(ui.ScrollWrapper(panel))

def save_and_sync(client):
    old_set = set(list_saves(save.get_save_dir()))
    client.chat('/save')
    ui.back()
    threading.Thread(target=save_and_sync_next_step, args=(old_set, )).start()

def list_saves(d):
    return [ n for n in os.listdir(d) if '.sav' in n ]

def save_and_sync_next_step(old_set):
    name_set = None
    start_time = time.time()
    stop = False
    while not stop:
        print 'finding save...'
        dir = save.get_save_dir()
        listing = list_saves(dir)
        new_set = set(listing)
        name_set = new_set - old_set
        if not name_set:
            for name in listing:
                mtime = os.path.getmtime(os.path.join(dir, name))
                if mtime > start_time:
                    stop = True
                    break
            time.sleep(0.5)
        else:
            stop = True
            name = iter(name_set).next()
            break
    print 'found save', name
    time.sleep(0.5)
    ui.execute_later.append(lambda: upload_save(save.get_save_dir() + '/' + name, name))

def upload_save(path, name):
    data = save.open_save(path).read()
    compressed = lzma.compress(data)
    if name.endswith('.gz'):
        name = name[:-3]
    request(uploaded_save, 'upload_content', 'android', name, compressed, banner='Uploading save... (%dkB)' % (len(compressed)/1024))

def uploaded_save(result):
    ui.set_dialog(ui.Label('Save uploaded.', ui.back))

def logout():
    request(lambda d: ui.back(), 'logout')

def download_sync(sha1):
    print 'downloading', sha1
    request(downloaded, 'download_content', sha1, banner='Downloading save...')

def downloaded(data):
    ui.set_dialog(ui.Label('Loading save...'))
    uncompressed = lzma.decompress(data)
    print 'Uncompressed size', len(uncompressed)
    dl_path = save.get_save_dir() + '/downloaded_save'
    try:
        os.remove(dl_path)
    except OSError:
        print 'not removed...'
    with open(dl_path, 'wb') as f:
        f.write(uncompressed)
    ui.back(anim=False)
    save.load_game(dl_path)

def show_login_form(callback):
    def logged(result):
        print 'Login successful'
        with open(save.get_save_dir() + '/civsync.sessid.txt', 'w') as f:
            f.write(session.sessid)
        ui.back(anim=False)
        callback()
    
    def do_login():
        request(logged, 'login', login_field.get_value(), passwd_field.get_value())
    
    def no_account():
        ui.message('Download Freeciv Sync for Desktop\nfrom freeciv.zielinscy.org.pl')
    
    panel = ui.LinearLayoutWidget()
    
    login = ui.HorizontalLayoutWidget()
    login.add(ui.Label('Login:'))
    login_field = ui.EditField()
    login.add(login_field)
    panel.add(login)
    
    passwd = ui.HorizontalLayoutWidget()
    passwd.add(ui.Label('Password:'))
    passwd_field = ui.EditField()
    passwd.add(passwd_field)
    panel.add(passwd)
    
    butts = ui.HorizontalLayoutWidget(spacing=10)
    butts.add(ui.Button('Login', do_login))
    butts.add(ui.Button('No account?', no_account))
    butts.add(ui.Button('Cancel', ui.back))
    panel.add(butts)
    
    ui.set(panel)

def comment(install_time, upload_log):
    if upload_log:
        content = lzma.compress(open(save.get_save_dir() + '/more.log').read())
        request(lambda result: comment_next(install_time), 'upload_log', content, install_time,
                banner="Uploading log (%dkB)" % (len(content)/1024))
    else:
        comment_next(install_time)

def comment_next(install_time):
    ui.back()
    uidialog.open_url('http://%s/comment?install_time=%s&sid=%s&ua=%s'
                      % (civsync.HOST, install_time, client()._sessid, civsync.USER_AGENT))

def client():
    global session
    
    if not session:
        try:
            sessid = open(save.get_save_dir() + '/civsync.sessid.txt').read().strip()
        except IOError:
            sessid = None
        session = civsync.Session(sessid)
    
    return session

def request(callback, name, *args, **kwargs):
    if 'banner' in kwargs:
        banner = kwargs['banner']
        del kwargs['banner']
    else:
        banner = 'Contacting server...'
    loading = ui.Label(banner)
    ui.set_dialog(loading)
    threading.Thread(target=sync_request, args=(callback, name, args, kwargs)).start()

def sync_request(callback, name, args, kwargs):
    func = getattr(client(), name)
    try:
        try:
            result = func(*args, **kwargs)
        except civsync.LoginError as err:
            print 'Login failed:', err
            ui.back(anim=False)
            self = lambda: request(callback, name, *args, **kwargs)
            ui.execute_later.append(lambda: show_login_form(self))
            return
    except Exception as err:
        traceback.print_exc()
        ui.back(anim=False)
        ui.execute_later.append(lambda: ui.message('Failed to connect to the internet'))
        return
    ui.back(anim=False)
    with ui.execute_later_lock:
        ui.execute_later.append(lambda: callback(result))

#ui.execute_later.append()
    