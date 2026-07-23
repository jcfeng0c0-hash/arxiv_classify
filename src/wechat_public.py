import requests
import json
import markdown
import time


def get_access_token(appid, secret):
    url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={appid}&secret={secret}"
    return requests.get(url).json().get("access_token")


def upload_thumb_image(access_token, img_path):
    url = f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={access_token}&type=image"
    with open(img_path, 'rb') as f:
        files = {'media': f}
        r = requests.post(url, files=files)
    res = r.json()
    if 'media_id' in res:
        return res['media_id']
    else:
        raise Exception("Cover image upload failed", res)


def upload_article_draft(access_token, title, author, content_html, digest, thumb_media_id):
    url = f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={access_token}"
    data = {
        "articles": [{
            "title": str(title),
            "author": str(author),
            "digest": str(digest),
            "show_cover_pic": 1,
            "content": str(content_html),
            "thumb_media_id": str(thumb_media_id),
            "content_source_url": "",
            "need_open_comment": 0,
            "only_fans_can_comment": 0
        }]
    }

    headers = {'Content-Type': 'application/json; charset=utf-8'}
    res = requests.post(url,
        data=json.dumps(data, ensure_ascii=False).encode('utf-8'),
        headers=headers)

    try:
        result = res.json()
    except Exception as e:
        raise Exception("Unable to parse WeChat response; possible encoding issue", res.text)

    if 'media_id' in result:
        return result['media_id']
    else:
        raise Exception("Draft upload failed: ", json.dumps(result, ensure_ascii=False, indent=2))


def publish_article(access_token, media_id):
    url = f"https://api.weixin.qq.com/cgi-bin/freepublish/submit?access_token={access_token}"
    res = requests.post(url, json={"media_id": media_id}).json()
    if 'publish_id' in res:
        return res['publish_id']
    else:
        raise Exception("Publish failed", res)


def get_publish_result(access_token, publish_id):
    url = f"https://api.weixin.qq.com/cgi-bin/freepublish/get?access_token={access_token}"
    res = requests.post(url, json={"publish_id": publish_id}).json()
    return res



TITLE = "2025-06-24.md"


#COVER_IMG_PATH = "cover.png"

#MARKDOWN_PATH = "./md/arxiv_2025-06-24.md"




def upload_main(MARKDOWN_PATH, TITLE='Arxiv Daily'):
    from src.config import WECHAT_APPID, WECHAT_SECRET, WECHAT_THUMB_MEDIA_ID
    appid = WECHAT_APPID
    secret = WECHAT_SECRET
    APPID = appid
    APPSECRET = secret
    AUTHOR = "your_name"
    DIGEST = "Arxiv Daily"

    access_token = get_access_token(APPID, APPSECRET)
    print("[1] access_token obtained successfully")
    thumb_media_id = WECHAT_THUMB_MEDIA_ID
    print("[2] Cover image uploaded successfully:", thumb_media_id)

    with open(MARKDOWN_PATH, 'r', encoding='utf-8') as f:
        md_text = f.read()
    html_text = markdown.markdown(md_text)


    media_id = upload_article_draft(access_token, TITLE, AUTHOR, html_text, DIGEST, thumb_media_id)
    print("[3] Article draft uploaded successfully:", media_id)
