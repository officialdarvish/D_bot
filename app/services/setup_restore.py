"""Compact first-run restore entry. Reuses the authenticated backup importer."""
import json


def markup():
    def field(key,en,fa,kind='password'):
        return f'<label><span data-en="{en}" data-fa="{fa}">{en}</span><input data-setup-restore="{key}" type="{kind}" autocomplete="off" dir="ltr"></label>'
    return '''<details class="setup-restore"><summary data-en="Have a backup? Restore backup" data-fa="بک‌آپ دارید؟ بازیابی بک‌آپ">Have a backup? Restore backup</summary><div class="setup-restore-body"><p data-en="For an existing bot on a new installation. Restoring replaces this installation’s data; its current web login and address are kept." data-fa="برای انتقال ربات قبلی به نصب تازه. بازیابی، داده‌های این نصب را جایگزین می‌کند؛ آدرس و ورود فعلی وب حفظ می‌شوند.">For an existing bot on a new installation. Restoring replaces this installation’s data; its current web login and address are kept.</p>'''+field('file','Backup file (.dbot / .json)','فایل بک‌آپ (.dbot / .json)','file')+'''<details class="setup-restore-keys"><summary data-en="Password or recovery keys (if needed)" data-fa="رمز یا کلید بازیابی (در صورت نیاز)">Password or recovery keys (if needed)</summary><div class="grid">'''+field('aes_password','Original backup password','رمز اصلی بک‌آپ')+field('recovery_key','Recovery key or key-list JSON','کلید بازیابی یا JSON فهرست کلیدها')+field('key_file','Recovery key-list file (optional)','فایل فهرست کلیدهای بازیابی (اختیاری)','file')+field('legacy_secret','Old FERNET_KEY / bot token (legacy backups only)','FERNET_KEY یا توکن ربات قدیمی (فقط بک‌آپ قدیمی)')+'''</div></details><p id="setupRestoreStatus" role="status" aria-live="polite"></p><button type="button" id="setupRestoreRun" class="btn" data-en="Restore this backup" data-fa="بازیابی این بک‌آپ">Restore this backup</button></div></details>'''


def script(prefix,csrf):
    return '<script>(()=>{const prefix='+json.dumps(prefix)+',csrf='+json.dumps(csrf)+r''';
    const box=document.querySelector('.setup-restore');if(!box)return;
    const file=box.querySelector('[data-setup-restore=file]');file.accept='.dbot,.json';box.querySelector('[data-setup-restore=key_file]').accept='.json,.txt';
    const status=document.getElementById('setupRestoreStatus'),button=document.getElementById('setupRestoreRun');let busy=false;
    const text=(en,fa)=>document.documentElement.lang==='fa'?fa:en;
    document.querySelector('main form').addEventListener('submit',e=>{if(busy){e.preventDefault();e.stopImmediatePropagation()}},true);
    button.onclick=async()=>{
      if(busy)return;status.textContent='';
      const selected=file.files[0];if(!selected){status.textContent=text('Choose a backup file first.','ابتدا فایل بک‌آپ را انتخاب کنید.');file.focus();return;}
      if(!/\.(dbot|json)$/i.test(selected.name)){status.textContent=text('Choose a .dbot or .json backup.','فایل بک‌آپ .dbot یا .json انتخاب کنید.');return;}
      if(!window.confirm(text('Restore this backup and replace the current database data?','این بک‌آپ بازیابی و جایگزین داده‌های فعلی شود؟')))return;
      const controls=[...document.querySelectorAll('main form input,main form select,main form textarea,main form button')].map(el=>[el,el.disabled]);
      busy=true;controls.forEach(([el])=>el.disabled=true);status.textContent=text('Restoring backup… Keep this page open.','در حال بازیابی بک‌آپ… این صفحه را باز نگه دارید.');
      try{
        const data=new FormData();data.set('file',selected);data.set('setup_restore','1');
        box.querySelectorAll('[data-setup-restore]').forEach(el=>{if(el.type!=='file'&&el.value)data.set(el.dataset.setupRestore,el.value)});
        const keys=box.querySelector('[data-setup-restore=key_file]').files[0];if(keys){if(keys.size>1048576)throw Error(text('Recovery key file is too large.','فایل کلید بازیابی بیش از حد بزرگ است.'));data.set('recovery_key',await keys.text())}
        const response=await fetch(prefix+'/admin/backup/restore',{method:'POST',credentials:'same-origin',redirect:'manual',headers:{Accept:'application/json','X-Requested-With':'fetch','X-CSRF-Token':csrf},body:data});
        const result=await response.json().catch(()=>null);
        if(response.status===401||response.type==='opaqueredirect')throw Error(text('Your session expired. Sign in again before restoring.','نشست ورود منقضی شده است؛ دوباره وارد شوید و بازیابی را انجام دهید.'));
        if(!response.ok||!result?.ok){const messages={backup_password_required:text('Enter the original backup password.','رمز اصلی بک‌آپ را وارد کنید.'),backup_key_required:text('Enter the recovery key or choose its key-list file.','کلید بازیابی یا فایل فهرست کلیدهای آن را وارد کنید.'),legacy_secret_required:text('Enter the old FERNET_KEY or bot token.','FERNET_KEY یا توکن ربات قدیمی را وارد کنید.'),legacy_secret_invalid:text('The old source key is incorrect.','کلید مبدأ قدیمی درست نیست.')};throw Error(messages[result?.code]||text('Restore failed. Check the backup file and its original keys.','بازیابی انجام نشد؛ فایل بک‌آپ و رمز یا کلید اصلی آن را بررسی کنید.'))}
        box.querySelectorAll('input').forEach(el=>el.value='');status.textContent=text('Backup restored. Opening your panel…','بک‌آپ بازیابی شد؛ در حال بازکردن پنل…');window.location.replace(prefix+'/admin');
      }catch(error){status.textContent=error.message||text('Restore failed.','بازیابی انجام نشد.');}
      finally{busy=false;controls.forEach(([el,disabled])=>el.disabled=disabled)}
    };
    })();</script>'''
