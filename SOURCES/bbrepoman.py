#!/usr/bin/python3
from datetime import datetime
import getopt
import getpass
import ipaddress
import json
import os
import pathlib
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import zipfile
import hashlib
import dbus
from tqdm import tqdm
import pdb

class RepoCache():
    
    cachedir = ''
    configdir = '/etc/BBrepomanager'
    wwwdir = '/srv/www'
    slpdir = '/etc/slp.reg.d'
    distros = {}
    initialized = False
    metadata_file = '/srv/www/htdocs/bbrepoman.json'
    age = 0
    default_owner = 'wwwrun'
    default_group = 'www'
    default_mode  = 0o755

    def __init__(self, cache_path):
        signal.signal(signal.SIGINT, self.cleanup)
        self.cachedir = cache_path
        if os.path.isdir(cache_path):
            # carrega o cache
            if (self.load_metadata()):
                 print(f'* metadados carregados ({self.metadata_file}, {str(len(self.distros))} distros)')
            else:
                self.scan_distros()
                self.write_metadata()

        else:
            print(f"* metadados não encontrados em {cache_path}")
            exit(1)

        return 
 
    def get_saved_checksums(self, dir):
        regex_checksums = r"(.*) \*?(.*)"
        match_dict = {}
    
        # Novo formato
        ckdir = os.path.join(self.configdir, dir + '.sha1sum.d')
    
        if os.path.isdir(ckdir):
            for filename in sorted(os.listdir(ckdir)):
                filepath = os.path.join(ckdir, filename)
    
                if not os.path.isfile(filepath):
                    continue
                
                with open(filepath, 'r') as f:
                    ck_content = f.read()
    
                matches_checksums = re.findall(
                    regex_checksums,
                    ck_content,
                    re.MULTILINE
                )
    
                for item in matches_checksums:
                    match_dict[item[1]] = item[0].strip()
    
            return match_dict
    
        # Formato legado
        ckfile = os.path.join(self.configdir, dir + '.sha1sum')
    
        if os.path.isfile(ckfile):
            with open(ckfile, 'r') as f:
                ck_content = f.read()
    
            matches_checksums = re.findall(
                regex_checksums,
                ck_content,
                re.MULTILINE
            )
    
            for item in matches_checksums:
                match_dict[item[1]] = item[0].strip()
    
        return match_dict

    def get_saved_distro_info(self, dir):   
        regex_desc=r"<distro name=.*description=\"(.*)\".*$"
        regex_target=r"<dir_target>(.*)</dir_target>"
        regex_slpd_name=r"<slpd_service_name>(.*)</slpd_service_name>"
        regex_slpd_path=r"<install_path>(.*)</install_path>"
        regex_slpd_port=r"<http_port>(.*)</http_port>"
        regex_slpd_id=r"<slpd_os_id>(.*)</slpd_os_id>"
        regex_slpd_ver=r"<slpd_os_version>(.*)</slpd_os_version>"
        
        
        distrofile = os.path.join(self.configdir, dir + '.xml')
        match_dict = {}
        if os.path.isfile(distrofile):
            with open(distrofile, 'r') as f:
                distro_content=f.read()
                
            desc = re.search(regex_desc, distro_content, re.MULTILINE)
            if desc is not None:
                match_dict['description'] = desc.group(1)
                
            target = re.search(regex_target, distro_content, re.MULTILINE)
            if target is not None:
                match_dict['target'] = target.group(1)
                
            slpd_name = re.search(regex_slpd_name, distro_content, re.MULTILINE)
            if slpd_name is not None:
                match_dict['slpd_name'] = slpd_name.group(1)
                
            slpd_path = re.search(regex_slpd_path, distro_content, re.MULTILINE)
            if slpd_path is not None:
                match_dict['slpd_path'] = slpd_path.group(1)
 
            slpd_port = re.search(regex_slpd_port, distro_content, re.MULTILINE)
            if slpd_port is not None:
                match_dict['slpd_port'] = slpd_port.group(1)
            else:
                match_dict['slpd_port'] = "80"
            slpd_id = re.search(regex_slpd_id, distro_content, re.MULTILINE)
            if slpd_id is not None:
                match_dict['slpd_id'] = slpd_id.group(1)
                
            slpd_ver = re.search(regex_slpd_ver, distro_content, re.MULTILINE)
            if slpd_ver is not None:
                match_dict['slpd_ver'] = slpd_ver.group(1)
               
        if match_dict is None:
            print(f'Erro ao obter dados da distro {dir} no XML!')
            return None
        return match_dict

    def scan_distros(self): 
        for root, dirs, files in os.walk(self.cachedir):
            for dir in dirs:
                repodir = os.path.join(self.cachedir, dir)
                flist = os.listdir(repodir)
                files = []
                matches_checksums = self.get_saved_checksums(dir)
                for f in flist:
                    if f in matches_checksums:
                        files.append({'filename': f, 'size': os.stat(os.path.join(repodir, f)).st_size, 'expected_checksum':matches_checksums[f], 'calculated_checksum':None})
                    else:
                        files.append({'filename': f, 'size': os.stat(os.path.join(repodir, f)).st_size, 'expected_checksum':None, 'calculated_checksum':None})
                d = {'name':dir,
                        'files': files,
                        'path': os.path.join(self.cachedir, dir)
                    }
                self.distros[dir] = d
            break   # break para processar apenas um nível

        return self.distros.keys()
    
    def touch_file(self, filename, permission, owner, group):
        try:
            with open(filename, "wt") as f:
                f.write('')
            os.chmod(filename, permission)
            shutil.chown(filename, owner, group)
        except Exception as e:
            raise(e)
        return True
    
    def delete_slpd_config(self, distro):
        # apaga arquivo antigo se existir
        slp_file =os.path.join(self.slpdir, distro + '.reg')
        if os.path.isfile(slp_file):
            os.remove(slp_file)
        return
    
    
    def write_slpd_config(self, distro):
        
        try:
            own_ip, own_netmask = self.get_own_ip()

            # busca informações do XML da distro, se existir
            distro_data = self.get_saved_distro_info(distro)
            
            if distro_data is None:
                print(f'* {self.color("*** ERRO ***", "red")} não é possível criar arquivo SLP para a distro "{distro}"')
                return False
            
            # apaga arquivo antigo se existir
            slp_file =os.path.join(self.slpdir, distro + '.reg')
            if os.path.isfile(slp_file):
                os.remove(slp_file)
                
            with open(slp_file, 'w') as f:
                f.write(f'# Repositório de instalação {distro} (gerado por BBrepomanager)\n')
                f.write(f'service:{distro_data["slpd_name"]}:http://{own_ip}:{distro_data["slpd_port"]}{distro_data["slpd_path"]},en,65535\n')
                f.write(f'watch-port-tcp={distro_data["slpd_port"]}\n')
                if 'description' in distro_data.keys():
                    f.write(f'description={distro_data["description"]}\n')
                else:
                    f.write(f'description=Repositório de instalação {distro}\n')
                    
                if 'slpd_id' in distro_data.keys() and 'slpd_ver' in distro_data.keys():
                    f.write(f'\n')
                    f.write(f'service:{distro_data["slpd_id"]}.{distro_data["slpd_ver"]}:http://{own_ip}:{distro_data["slpd_port"]}{distro_data["slpd_path"]},en,65535\n')
                    f.write(f'watch-port-tcp={distro_data["slpd_port"]}\n')
                    if 'description' in distro_data.keys():
                        f.write(f'description={distro_data["description"]}\n')
                    else:
                        f.write(f'description=Repositório de instalação {distro}\n')
                
            # cria flag
            # self.touch_file(os.path.join(self.wwwdir, distro + '.flag'), 0o644, 'wwwrun', 'www')
            
        except IOError:
            print(f'* {self.color("*** ERRO ***", "red")} não é possível criar arquivo SLP para a distro "{distro}"')
            return False
        return True
    
            
    def color(self, text, color, bold=True):
        esc = '\x1b['
        ret = ""
        if bold:
            ret += esc + '1m'
        reset = esc + '0m'
        if color == 'red':
            ret += esc + '31m' + text + reset
        elif color == 'green':
            ret += esc + '32m' + text + reset
        elif color == 'yellow':
            ret += esc + '33m' + text + reset
        elif color == 'blue':
            ret += esc + '34m' + text + reset
        elif color == 'magenta':
            ret += esc + '35m' + text + reset
        elif color == 'cyan':
            ret += esc + '36m' + text + reset
        else:
            return text
        return ret
        
    def list_distros(self):
        print(f"Cache de repositórios ({self.cachedir})")
        print('-' * 80)

        for distro in self.distros.keys():
            print(f"Distro:\t{distro} ({self.distros[distro]['path']})")
            if 'timestamp_cache' in self.distros[distro].keys() and self.distros[distro]['timestamp_cache'] is not None:
                age = (datetime.strptime(self.distros[distro]['timestamp_cache'], "%Y-%m-%dT%H:%M:%S.%f") - datetime.now()).days + 1
                print(f"Última verificação do cache: ({age} dias)")
            else:
                print(f"Última verificação do cache: (nunca)")
            if 'timestamp' in self.distros[distro].keys() and self.distros[distro]['timestamp'] is not None:
                age = (datetime.strptime(self.distros[distro]['timestamp'], "%Y-%m-%dT%H:%M:%S.%f") - datetime.now()).days + 1
                print(f"Última verificação dos arquivos: ({age} dias)")
            else:
                print(f"Última verificação dos arquivos: (nunca)")


            print(f"Arquivos:")
            for f in self.distros[distro]['files']:
                print(f"\t{f['filename']}  ({f['size']} bytes)")
                if f['calculated_checksum'] is None or f['expected_checksum'] is None:
                    print(f"\t\tSHA1: (execute uma verificação para atualizar)")
                else:
                    if f['calculated_checksum'] != f['expected_checksum']:
                        print(f"\t\tSHA1: {f['calculated_checksum']} *** {self.color('INCORRETO', 'red')} *** (esperado: {self.color(f['expected_checksum'], 'yellow')})")
                    else:
                        print(f"\t\tSHA1: {f['calculated_checksum']} ({self.color('OK', 'green')})")
            print()
        return

    # retorna o próprio IP
    def get_own_ip(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        try:
            # doesn't even have to be reachable
            s.connect(('10.255.255.255', 1))
            ip = s.getsockname()[0]
        except Exception:
            ip = '127.0.0.1'
        finally:
            s.close()

        netmask = str(ipaddress.IPv4Network(ip).netmask)

        return ip, netmask

    def discard_metadata(self):
        print(f'* descartando metadados')
        self.distros = {}
        return
    
    def load_metadata(self):
        try:
            if not self.initialized:
                with open(self.metadata_file, "r") as f:
                    self.distros = json.loads(f.read())
                self.initialized = True
        except IOError:
            print(f'* erro ao ler metadados de {self.metadata_file} (não fatal)')
            return False
        except json.decoder.JSONDecodeError:
            print('* metadados inválidos (não fatal)')
            # print('Dados lidos: ' + '[' + self.distros + ']')
            return False
        
        
        # preenche os checksums conhecidos
        for distro in self.distros.keys():
            matches_checksums = self.get_saved_checksums(distro)
            distro_data = self.get_saved_distro_info(distro)
            self.distros[distro]['install_path'] = distro_data['slpd_path']
            for f in self.distros[distro]['files']:
                if f['filename'] in matches_checksums:
                    f['expected_checksum'] = matches_checksums[f['filename']]
    
        return True

    def restart_service(self, service_name):
        bus = dbus.SystemBus()
        systemd1 = bus.get_object('org.freedesktop.systemd1', '/org/freedesktop/systemd1')
        manager = dbus.Interface(systemd1, 'org.freedesktop.systemd1.Manager')
        job = manager.RestartUnit(service_name, 'fail')
        return
        
    def write_metadata(self):
        try:
            print(f'* metadados atualizados ({self.metadata_file}, {str(len(self.distros))} distros)')
            if not os.path.exists(os.path.dirname(self.metadata_file)):
                os.mkdir(os.path.dirname(self.metadata_file), mode=755)
            with open(self.metadata_file, "w+") as f:
                f.write(json.dumps(self.distros,
                        default=self.dt_parser))
        except IOError:
            print(f'* erro ao salvar metadados em {self.metadata_file} (não fatal)')
            return False
        return True
    
    def get_distro_list(self):
        return self.distros.keys()

    def dt_parser(self, dt:datetime):
        if isinstance(dt, datetime):
            return dt.isoformat()    
            
    def set_permissions(self, path):
        try:
            for dirpath, dirnames, filenames in os.walk(path):
                print(f'* alterando atributos para diretório {dirpath}', end='')
                shutil.chown(dirpath, self.default_owner, self.default_group)
                os.chmod(path, self.default_mode)
                for filename in filenames:
                    # print(f'* alterando atributos para arquivo {filename}')
                    print('.', end='')
                    shutil.chown(os.path.join(dirpath, filename), self.default_owner, self.default_group)
                    os.chmod(path, self.default_mode)
                print()
        except Exception as e:
            print(f'*** ERRO *** ao definir atributos: {e} ')
        return                
                
    def extract_all(self, distro, destination='/'):
        if distro not in self.distros.keys():
            print(f'*** {self.color("ERRO", "red")} ***: "{distro}" não consta da lista de distros conhecidas.')
            return False
        try:
            print(f'---> Processando "{distro}"...')
            for f in self.distros[distro]['files']:
                print(f'---> Descompactando arquivo: {f["filename"]} ({f["size"]} bytes)')
                filename = os.path.join(self.distros[distro]['path'], f['filename'])
                if filename.endswith('.zip'):
                    self.extract_zipfile(filename, destination)
                elif filename.endswith('.tar.gz') or filename.endswith('.tgz'):
                    self.extract_tarfile(filename, destination)
            
            # verifica se o arquivo de checksums foi incluido no repositório
            catalogs,missing_catalogs=self.get_checksum_catalogs(distro)
            if (len(missing_catalogs) > 0):
                print(f'---> Alguns repositórios não possuem checksums, gerando catálogos...')
                self.generate_checksum_catalogs(distro, missing_catalogs)
            
        except Exception as e:
            print(f'Erro ao descompactar arquivo: {e}')
            return False
        return True        

    def generate_checksum_catalogs(self, distro, missing_catalogs):
        sha1 = []
        if distro not in self.distros.keys():
            print(f'*** {self.color("ERRO", "red")} ***: "{distro}" não consta da lista de distros conhecidas.')
            return False
        try:
            print(f'---> Criando checksums para "{distro}"...')
            for f in missing_catalogs:
                sha1 = []
                # gera o arquivo de checksums
                print(f'Gerando catálogo SHA1SUM faltante em {f}...')
                os.chdir(os.path.dirname(f))                
                # files = [f for f in pathlib.Path(".").rglob("*") if f.is_file()]
                files = [
                    f for f in pathlib.Path(".").rglob("*")
                    if f.is_file() and f.suffix.lower() == ".rpm"
                ]
                with tqdm(total=len(files), position=1, unit='files') as pbar:
                    for p in files:
                        # if os.path.isdir:
                        if p.is_dir():
                            continue
                        sha1_value = self.do_sha1sum(p)
                        if sha1_value is None:
                            continue
                        sha1.append(self.do_sha1sum(p)  + '  ' + str(p) + '\n')
                        pbar.update()

                with open('CHECKSUMS', 'w') as file:
                    file.writelines(sha1)
        except Exception as e:
            print(f'Erro ao gerar sha1sum: {e}')
            return False
    
        return True
    
    def get_checksum_catalogs(self, distro):
        basedir_system='/srv/www' + self.distros[distro]['install_path'].rstrip('/').rpartition('/')[0]
        basedir_other=basedir_system.rstrip('/').rpartition('/')[0].rpartition('/')[0]
        if distro not in self.distros.keys():
            print(f'*** {self.color("ERRO", "red")} ***: "{distro}" não consta da lista de distros conhecidas.')
            return None
        try:
            print(f'---> Processando "{distro}"...')
            catalogs=[]
            missing_catalogs=[]
            distro_path = distro.replace("SLE", "").replace("SP", "sp").lower()

            for f in self.distros[distro]['files']:
                if os.path.basename(f['filename']).startswith('sistema'):
                    system_catalog=os.path.join(basedir_system, 'CHECKSUMS')
                    print(basedir_system)
                    print(system_catalog)
                    if os.path.exists(system_catalog):
                        print(f'---> Achei catalogo de sistema no arquivo: {system_catalog}')
                        catalogs.append(system_catalog)
                        continue
                    else:
                        print(f'Não consegui encontrar CHECKSUMS para o arquivo de sistema')
                        missing_catalogs.append(system_catalog)
                else:
                    # print(os.path.basename(f['filename']).partition('-')[0])
                    repositorio = str(os.path.basename(f['filename']).partition('-')[0].partition('.')[0])
                    # print(f'Repositorio: {repositorio} , Distro {distro}')
                    
                    if repositorio == "install" or repositorio == "backports":
                            filename = os.path.join(os.path.join(basedir_other,"sistema",distro_path,os.path.basename(f['filename']).partition('-')[0].partition('.')[0]+'-x86_64'), 'CHECKSUMS')
                    elif repositorio == "tmf":
                            filename = os.path.join(os.path.join(basedir_other,"bb","tmf-ag"), 'CHECKSUMS')
                    elif repositorio == "packagehub":
                            filename = os.path.join(os.path.join(basedir_other,"sistema",distro_path,"SLE-Module-Packagehub-Subpackages-x86_64"), 'CHECKSUMS')
                    else:
                            filename = os.path.join(os.path.join(basedir_other,"bb",os.path.basename(f['filename']).partition('-')[0].partition('.')[0]), 'CHECKSUMS')

                    if os.path.exists(filename):
                        print(f'---> Achei catálogo no arquivo: {filename}')
                        catalogs.append(filename)
                        continue
                    else:
                        print(f"Não consegui encontrar CHECKSUMS para o arquivo {f['filename']}")
                        missing_catalogs.append(filename)
        except Exception as e:
            print(f'Erro ao listar arquivo: {e}')
            return None
        return catalogs, missing_catalogs    


    def delete_all(self, distro, destination='/'):
        if distro not in self.distros.keys():
            print(f'*** {self.color("ERRO", "red")} ***: "{distro}" não consta da lista de distros conhecidas.')
            return False
        try:
            print(f'---> Processando "{distro}"...')
            to_delete = []
            for f in self.distros[distro]['files']:
                print(f'---> Obtendo lista de arquivos a partir de {f["filename"]} ({f["size"]} bytes)')
                filename = os.path.join(self.distros[distro]['path'], f['filename'])
                if filename.endswith('.zip'):
                    to_delete = to_delete + self.list_zipfile(filename)
                elif filename.endswith('.tar.gz') or filename.endswith('.tgz'):
                    to_delete = to_delete + self.list_tarfile(filename)
            print(f'*** Todos os arquivos da distro {distro} serão {self.color("APAGADOS", "red")} ***')
            print(f'---> Total de {len(to_delete)} arquivos a deletar.')
            g = input(f'   {self.color("Deseja continuar (S/N)?", "yellow")}   ')
            if g in ["S", "s", "SIM", "sim"]:
                for f in to_delete:
                    file = os.path.join('/', f)
                    if os.path.isfile(file):
                        print(f'apagando {file}')
                        os.remove(file)
                    else:
                        print(f'ignorando diretório {file}')
                print(f'---> Arquivos apagados com sucesso.')
            else:
                print('---> Operação abortada.')
                return False
        except Exception as e:
            print(f'Erro ao processar arquivo: {e}')
            return False
        return True 

    def list_zipfile(self, filename):
        files=[]
        with zipfile.ZipFile(filename) as zf:
            for member in zf.infolist():
                files.append(member.filename)
        return files
    
    def list_tarfile(self, filename):
        files=[]
        with tarfile.open(filename, mode='r:gz') as tf:
            for member in tf.getmembers():
                files.append(member.name)
        return files
                    
    def extract_zipfile(self, filename, destination):
        with zipfile.ZipFile(filename) as zf:
            files=zf.infolist()
            with tqdm(total=len(files), desc=f'Extraindo {filename} ', unit='files') as pbar:
                for member in files:
                    try:
                        pbar.update()
                        pbar.set_description(os.path.basename(member.filename))
                        zf.extract(member, destination)
                    except zipfile.error as e:
                        print(f'*** ERRO *** ao extrair arquivo {member}')
                    
        return

    def extract_tarfile(self, filename, destination):
        with tarfile.open(filename, mode='r:gz') as tf:
            files=tf.getmembers()
            with tqdm(total=len(files), desc=f'Extraindo {filename} ', unit='files') as pbar:
                for member in files:
                    try:
                        pbar.update()
                        pbar.set_description(os.path.basename(member.name))
                        tf.extract(member, destination)
                    except tarfile.ExtractError as e:
                        print(f'*** ERRO *** ao extrair arquivo {member}')
        return

    def do_sha1sum(self, filename):
        print(f"Calculando checksum para {filename}...")
        BUF_SIZE = 4 * 1024 * 1024 # tamanho do buffer para o digest (4MB)
        sha1 = hashlib.sha1()
        if os.path.isdir(filename):
            print(f'não posso calcular checksum para diretório: {filename}')
            return None
        if not os.path.exists(filename):
            print(f'arquivo {filename} não existe')
            return None
        with open(filename, 'rb') as f:
            size = os.stat(filename).st_size
            with tqdm(total=size, unit='B', unit_scale=True, unit_divisor=1024, leave=False, position=0) as pbar:
                pbar.set_description(f'Calculando checksum: {filename}')
                while True:
                    data = f.read(BUF_SIZE)
                    if not data:
                        break
                    sha1.update(data)
                    pbar.update(len(data))
        return sha1.hexdigest()
 
    def do_sha1sum_catalog(self, checksum_catalog):
        BUF_SIZE = 4 * 1024 * 1024 # tamanho do buffer para o digest (4MB)
        with open(checksum_catalog, 'r') as f:
            checksum_data = f.readlines()
        
        basedir=os.path.dirname(checksum_catalog)
        pbar_files = tqdm(total=len(checksum_data), unit='files', bar_format='{l_bar}{bar}{r_bar:>60}', position=1, leave=False)
        pbar_files.update()
        for entry in checksum_data:
            item = entry.split()
            pbar_files.set_description(f'Verificando: {os.path.basename(item[1])}')
            print(f'Verificando: {os.path.basename(item[1])}')
            if os.path.basename(item[1]) == 'CHECKSUMS':
                pbar_files.update()
                continue
            expected_checksum = item[0]
            sha1 = hashlib.sha1()
            with open(os.path.join(basedir, item[1]), 'rb') as p:
                while True:
                    data = p.read(BUF_SIZE)
                    if not data:
                        break
                    sha1.update(data)
                calculated_checksum = sha1.hexdigest()
            if calculated_checksum != expected_checksum:
                print(f"***  SHA1: {self.color('INCORRETO', 'red')} *** (esperado: {self.color(expected_checksum, 'yellow')}, calculado: {calculated_checksum})")
                return False
            else:
                pbar_files.update()
                
        pbar_files.close()
        return True
           
    def verify_checksums(self, distro_name):
        # verifica o cache para a distro selecionada...
        print(f"* PRIMEIRA FASE: integridade do cache")
        if self.verify_cache_checksums(distro_name):
            # verifica a integridade dos arquivos...
            print(f"* SEGUNDA FASE: integridade dos arquivos individuais")
            return self.verify_file_checksums(distro_name)
        else:
            return False
        
    def verify_cache_checksums(self, distro_name):

        if distro_name not in self.distros.keys():
            print(f"Distro {distro_name} não existe")
            return False
        else:
            failed = False
            print(f"* Verificando estado do cache para {distro_name}...")
            for item in self.distros[distro_name]['files']:
                if os.path.isdir(os.path.join(self.distros[distro_name]['path'], item['filename'])):
                    print(f"{item['filename']} é um diretório, pulando.")
                    continue
                item['calculated_checksum'] = self.do_sha1sum(os.path.join(self.distros[distro_name]['path'], item['filename']))
                if item['calculated_checksum'] != item['expected_checksum']:
                    print(f"*** {self.color('INCORRETO', 'red')} *** (esperado: {self.color(item['expected_checksum'], 'yellow')}, calculado: {item['calculated_checksum']})")
                    failed = True
                else:
                    print(f"SHA1: {item['filename']} {item['calculated_checksum']} ({self.color('OK', 'green')})")
                    # atualiza o timestamp
                    self.distros[distro_name]['timestamp_cache'] = datetime.now()
                    
                print()
                # atualiza o timestamp
                if failed:
                    self.distros[distro_name]['timestamp_cache'] = None
                                    
        if failed:
            print(f"* Cache para {distro_name} {self.color('INVÁLIDO', 'red')}")
            return False

        print(f"* Cache para {distro_name} {self.color('INTEGRO', 'green')}")
        return True
    
    def verify_file_checksums(self, distro_name):
        if distro_name not in self.distros.keys():
            print(f"Distro {distro_name} não existe")
            return False
        else:
            catalogs, missing_catalogs=self.get_checksum_catalogs(distro_name)
            if len(missing_catalogs) > 0:
                for c in missing_catalogs:
                    print(f"*** {self.color(f'Arquivo de checksums {c} não existe', 'yellow')}")
                print(f"*** {self.color('ERRO', 'red')}: recomendado extrair a distribuição {distro_name} novamente do cache.")
                self.distros[distro_name]['timestamp'] = None
                return False      
                
            pbar_catalogs = tqdm(total=len(catalogs), unit='files', bar_format='{l_bar}{bar}{r_bar:>60}', position=0, leave=False)
            pbar_catalogs.update()
            for checksum_catalog in catalogs:
                pbar_catalogs.set_description(f'Catálogo: {checksum_catalog}')
                if os.path.exists(checksum_catalog):
                    if self.do_sha1sum_catalog(checksum_catalog) is False:
                        # remove a configuração da distro que deu problema e reinicia o SLPD
                        self.delete_slpd_config(distro_name)
                        self.restart_service('slpd.service')
                        print(f'* reiniciando serviço SLPD ({self.color("OK", "green")})')
                        self.distros[distro_name]['timestamp'] = None
                        return False
                else:
                    print(f"*** {self.color(f'Arquivo de checksums {checksum_catalog} não existe', 'yellow')}")
                    print(f"*** {self.color('ERRO', 'red')}: recomendado extrair a distribuição {distro_name} novamente do cache.")
                    self.distros[distro_name]['timestamp'] = None
                    return False      
                pbar_catalogs.update()
            pbar_catalogs.close()
            print()
                
            # tudo ok, atualiza o timestamp
            self.distros[distro_name]['timestamp'] = datetime.now()
            print(f"*** {distro_name}: {self.color('INTEGRO', 'green')}")

        # tudo ok, gera flag e configuração do SLP        
        if (self.write_slpd_config(distro_name)):
            print(f'* criando arquivos SLP para distro "{distro_name}" ({self.color("OK", "green")})')
   
        # reinicia o SLPD
        self.restart_service('slpd.service')
        print(f'* reiniciando serviço SLPD ({self.color("OK", "green")})')
            
        return True
        
    def sync_repo(self, remote_addr):
        
        username = input(f'Usuário para {remote_addr}: ')
        cmdline_listfiles = f'/usr/bin/rsync --list-only -e "/usr/bin/ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null" {username}@{remote_addr}:/srv/www/cache/'
        proc = subprocess.Popen(cmdline_listfiles, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        output, err = proc.communicate()
        regex = r"^d[rwxs-]+.*[0-9]+\:[0-9]{2}\s+(.*)"
        if output is not None:
            match = re.findall(regex, output.decode('utf-8'), re.MULTILINE)
            if match is not None:
                for item in  match:
                    if item == '.':
                        match.remove(item)

                print(f"Repositórios disponíveis:")
                count=0
                for item in match:
                    print(f'{count} - {item}')
                    count = count + 1                
                sel = input('Selecione um repositório: ')
                print('* Iniciando rsync...')                
                cmdline_sync=f'rsync -avvz --progress {username}@{remote_addr}:/srv/www/cache/{match[int(sel)]}/ /srv/www/cache/{match[int(sel)]}/'
                os.system(cmdline_sync)
                
                print('* Copiando catálogos...')
                cmdline_catalog=f'scp {username}@{remote_addr}:/etc/BBrepomanager/{match[int(sel)]}* /etc/BBrepomanager/.'
                os.system(cmdline_catalog)
                
        return True
        
    def set_checksum(self, distro_name, filename, checksum):
        if distro_name not in self.distros.keys():
            print(f"Distro {distro_name} não existe")
            return False
        else:
            for f in self.distros[distro_name]['files']:
                if f['filename'] == filename:
                    f['expected_checksum'] = checksum
                    return True
        return False

    def cleanup(self, signalNumber, frame):
        print('\nok, ok, saindo!')
        sys.exit(1)
        return
    
#_#_#_#_#_#_#_#_#_#_#_#_#


class BBRepoMan():
    version = '2.0'
    build = '202401124'

    def usage(self):
        print('Uso: ' + sys.argv[0] + ' [-l|--list] [-c|--verify-cache] [-v|--verify <repositório>|all] [-e|--extract <repositório>] [-r|--rescan] [-s|--setpermissions] [-d|--delete <repositorio>] [-S|--sync <servidor remoto>] [-V|--version]')
        return

    def show_version(self):
            print('BB Repo Manager versão ' + self.version + '-' + self.build + ' by Erico Mendonca <erico.mendonca@suse.com>\n')
            return

    def show_help(self):
        self.usage()
        print('\n')
        print('-h|--help\t\t\tExibe este texto de ajuda')
        print('-l|--list\t\t\tExibe todos os repositórios disponíveis no cache')
        print('-c|--verify-cache <repositorio>|all\tVerifica o estado do cache para o repositório especificado.')
        print('-v|--verify <repositório>|all\tVerifica os checksums dos arquivos para o repositório especificado.')
        print('-e|--extract <repositório>|all\tExtrai os arquivos de uma distro, ou de todas as distros')
        print('-d|--delete <repositório>|all\tApaga todos os arquivos relacionados a uma distro, ou de todas as distros.')
        print('-r|--rescan\t\t\tDescarta os metadados e escaneia novamente por distros.')
        print('-s|--setpermissions\t\tAltera o dono/grupo e aplica permissões em /srv/www')
        print('-S|--sync <servidor remoto>\tSincroniza o cache a partir de outra máquina via RSYNC')
        print('-V|--version\t\t\tExibe a versão e o build do programa.')
        print('\n')
        return


## programa principal ##
def main(): 
    
    bbr = BBRepoMan()
    
    try:
        opts, args = getopt.getopt(sys.argv[1:],  "Vhv:c:e:lrsd:S:", ["version", "help", "verify=", "verify-cache=", "extract=", "list", "rescan", "setpermissions", "delete", "sync="])
    except getopt.GetoptError as err:
        print(err)
        bbr.usage()
        exit(2)
    
    if len(sys.argv) < 2:
        bbr.usage()
        exit(2)
    
    if 'verificar' in sys.argv or 'status' in sys.argv or 'listar' in sys.argv or 'extrair' in sys.argv or 'limpar' in sys.argv:
        print("*** O BBrepomanager mudou! Use a nova sintaxe.")
        bbr.usage()
        exit(2)
        
    c = RepoCache('/srv/www/cache')
    verify_repo = ''
    
    for o, a in opts:
        if o in ("-h", "--help"):
            bbr.show_help()
            exit(1)
        if o in ("-V", "--version"):
            bbr.show_version()
            exit(1)
        elif o in ("-c", "--verify-cache"):
            verify_repo = a
            # tratamento para verify            
            if verify_repo != '' and verify_repo != 'all':
                c.verify_cache_checksums(verify_repo)
                c.write_metadata()
            elif verify_repo == 'all':
                for distro in c.get_distro_list():
                    print(f"*** Verificando checksums para {distro}...")
                    c.verify_cache_checksums(distro)
                    c.write_metadata()
            
        elif o in ("-v", "--verify"):
            verify_repo = a
            # tratamento para verify            
            if verify_repo != '' and verify_repo != 'all':
                c.verify_checksums(verify_repo)
                c.write_metadata()
            elif verify_repo == 'all':
                for distro in c.get_distro_list():
                    print(f"*** Verificando checksums para {distro}...")
                    c.verify_checksums(distro)
                    c.write_metadata()
        elif o in ("-e", "--extract"):
            extract_repo = a
            # tratamento para extract
            if extract_repo != '' and extract_repo != 'all':
                c.extract_all(extract_repo)
            elif extract_repo == 'all':
                for distro in c.get_distro_list():
                    print(f"*** Extraindo arquivos para {distro}...")
                    c.extract_all(distro)
            # define permissões padrão
            c.set_permissions('/srv/www')
        elif o in ("-l", "--list"):
            c.list_distros()
        elif o in ("-r", "--rescan"):
            c.discard_metadata()
            c.scan_distros()
            c.write_metadata()
            c.list_distros()
        elif o in ("-s", "--setpermissions"):
            c.set_permissions('/srv/www')
        elif o in ("-S", "--sync"):
            remote_addr = a
            c.sync_repo(remote_addr)
        elif o in ("-t", "--test"):
            c.test()
        elif o in ("-d", "--delete"):
            clean_repo = a
            # tratamento para clean
            if clean_repo != '' and clean_repo != 'all':
                c.delete_all(clean_repo)
            elif clean_repo == 'all':
                for distro in c.get_distro_list():
                    print(f"*** Apagando arquivos para {distro}...")
                    c.delete_all(distro)
        else:
            assert False, "opção inválida"

        print('---> Finalizado.')
    return

if __name__ == "__main__":
    main()


