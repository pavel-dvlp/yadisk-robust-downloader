import argparse
import json
import os
import urllib.request
import socket

client_id = "0600fcb8a139447a9211b35d0bc630e6"
client_secret = ""
code_request_uri = ("https://oauth.yandex.ru/authorize?"
                    f"response_type=code&force_confirm&client_id={client_id}&"
                    "redirect_uri=https://oauth.yandex.ru/verification_code")


def download_file(url: str, local_path: str, timeout: int = 3) -> bool:
    req = urllib.request.Request(url)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            with open(local_path, 'wb') as local_file:
                while chunk := response.read(8192):
                    local_file.write(chunk)
        print("Файл успешно скачан!")
        return True
    except urllib.error.HTTPError as e:
        print(f"Ошибка HTTP {e.code}")
        print("Ответ сервера:", e.read().decode('utf-8', errors='ignore'))
    except urllib.error.URLError as e:
        if isinstance(e.reason, socket.timeout) or isinstance(e.reason, TimeoutError):
            print('Ошибка: Превышено время ожидания ответа от сервера!')
        else:
            print(f'Ошибка: {e.reason}')
    except socket.timeout as e:
        print('Ошибка: Превышено время ожидания ответа от сервера!')
    return False


def get_download_link(path: str, access_token: str) -> str:
    params = {'path': path}
    url = "https://cloud-api.yandex.net/v1/disk/resources/download?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method='GET')
    req.add_header('Authorization', 'Bearer ' + access_token)
    with urllib.request.urlopen(req, timeout=5) as response:
        r = response.read().decode('utf-8')
        r2 = json.loads(r)
        return r2["href"]


def get_file_list(offset: int, access_token: str) -> list:
    list_fields = "items.path,items.modified,items.size"
    list_url = f"https://cloud-api.yandex.net/v1/disk/resources/files?fields={list_fields}&offset={offset}&path=/"
    req = urllib.request.Request(list_url, method='GET')
    req.add_header('Authorization', 'Bearer ' + access_token)
    with urllib.request.urlopen(req, timeout=30) as response:
        r = response.read().decode('utf-8')
        r2 = json.loads(r)
        return r2["items"]


def get_access_token(code: str):
    get_token_uri = "https://oauth.yandex.ru/token"

    print("Запрос " + get_token_uri)
    get_token_form_data = {
        'grant_type': 'authorization_code',
        'code': code,
        'client_id': client_id,
        'client_secret': client_secret
    }

    encoded_data = urllib.parse.urlencode(get_token_form_data).encode('utf-8')

    req = urllib.request.Request(get_token_uri, data=encoded_data, method='POST')
    req.add_header('Content-type', 'application/x-www-form-urlencoded')

    resp_string = verbose_request(req)
    resp = json.loads(resp_string)
    return resp["access_token"]


def verbose_request(req: urllib.request.Request) -> str:
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        # 3xx, 4xx, 5xx
        print(f'Произошла ошибка HTTP. Статус-код: {e.code}')
        print(f'Причина (Reason): {e.reason}')

        error_body = e.read().decode('utf-8')
        print('Тело ответа сервера с ошибкой:')
        print(error_body)
        raise e

    except urllib.error.URLError as e:
        print('Ошибка сети или неверный URL:', e.reason)
        raise e
    except Exception as e:
        print('Ошибка при запросе:', e)
        raise e


parser = argparse.ArgumentParser()
parser.add_argument("--token", type=str, help="OAuth token", default=None)
parser.add_argument("--offset", type=int, help="offset", default=0)
parser.add_argument("--timeout", type=int, help="timeout for connect", default=3)
parser.add_argument("--list", type=bool, help="Only save file list", default=False)
parser.add_argument("--scan", type=bool, help="Only scan file list vs real fs", default=False)
parser.add_argument("--fix-size", type=bool, help="Only redownload file with bad size", default=False)
parser.add_argument("--base-dir", type=str, help="Base dir for saving downloaded files")

args = parser.parse_args()
base_path = args.base_dir
offset = args.offset

if args.token is None:
    print("Для входа в аккаунт получите код по ссылке")
    print(code_request_uri)
    print()
    code = input("Введите код авторизации: ").strip()

    print("Авторизация...")
    access_token = get_access_token(code)
else:
    access_token = args.token
print("Получен OAuth token: " + access_token)

limit = 20
success = 0
list_path = os.path.join(base_path, "yadisk-robust-downloader-file-list.txt")

if not os.path.exists(list_path):
    directory = os.path.dirname(list_path)
    os.makedirs(directory, exist_ok=True)
    with open(list_path, 'w', encoding="utf-8") as list_file:
        while True:
            file_list = get_file_list(offset, access_token)
            print(f"Получили список для offset = {offset}")
            for item in file_list:
                print(item["path"] + '\t' + str(item["modified"]) + '\t' + str(item["size"]), file=list_file)
            if len(file_list) < limit:
                break
            offset += limit

if args.list:
    exit(0)

cloud_paths = list()
sizes = dict()
with open(list_path, "r", encoding="utf-8") as f:
    for line in f:
        # Убираем лишние пробелы/переносы строк на концах и делим по табу
        values = line.strip().split("\t")
        if len(values) > 0:
            p = values[0].strip().removeprefix("disk:")
            size = int(values[2].strip())
            if len(p) > 0:
                cloud_paths.append(p)
                sizes[p] = size

if args.scan:
    exists = 0
    bad_size = 0
    for cloud_path in cloud_paths:
        local_path = os.path.normpath(base_path + cloud_path)
        if os.path.exists(local_path):
            exists += 1
            size_in_bytes = os.path.getsize(local_path)
            if size_in_bytes != sizes[cloud_path]:
                bad_size += 1
    print(f"Всего файлов в облаке {len(cloud_paths)}, из них в {base_path} есть "
          f"{exists}/{len(cloud_paths)} ({int(exists*100/len(cloud_paths))}%), неправильный размер имеют {bad_size} файлов")
    exit(0)

print("Качаем согласно имеющемуся списку")
print(f"Есть {len(cloud_paths)} файлов в списке")
k = offset
for cloud_path in cloud_paths:
    if k > 0:
        k -= 1
        continue
    local_path = os.path.normpath(base_path + cloud_path)
    offset += 1
    timeout = args.timeout
    if os.path.exists(local_path):
        size_in_bytes = os.path.getsize(local_path)
        if size_in_bytes == sizes[cloud_path]:
            continue
        else:
            timeout *= 2  # more time for available file
            print(f"Файл {local_path} уже существует, но имеет неверный размер {size_in_bytes} вместо {sizes[cloud_path]}")
    else:
        if args.fix_size:
            continue

    try:
        link = get_download_link(cloud_path, access_token)
        directory = os.path.dirname(local_path)
        os.makedirs(directory, exist_ok=True)
        print(f"N {offset}. Download file {cloud_path} to {local_path}")
        if download_file(link, local_path, timeout):
            success += 1
    except Exception as e:
        print("exception: ", e)

    if os.path.exists(local_path):
        size_in_bytes = os.path.getsize(local_path)
        if size_in_bytes != sizes[cloud_path]:
            print(f"Файл {local_path} создан, но имеет неверный размер {size_in_bytes} вместо {sizes[cloud_path]}")
    else:
        print(f"Файл {local_path} не создан")
    print("-------")
print(f"скачано {success}")

#
# print("Получаем список файлов и пытаемся качать")
#
# while True:
#     file_list = get_file_list(offset, access_token)
#     print(f"Получили список для offset = {offset}")
#     for item in file_list:
#         cloud_path = str(item["path"]).removeprefix("disk:")
#         local_path = os.path.normpath(base_path + cloud_path)
#         if os.path.exists(local_path):
#             pass
#         else:
#             try:
#                 link = get_download_link(cloud_path, access_token)
#                 directory = os.path.dirname(local_path)
#                 os.makedirs(directory, exist_ok=True)
#                 print(f"Download file {cloud_path} to {local_path}")
#                 if download_file(link, local_path):
#                     success += 1
#             except Exception as e:
#                 print("exception")
#                 pass
#
#     if len(file_list) < limit:
#         break
#     offset += limit
# print(f"Успешно скачано {success}")
