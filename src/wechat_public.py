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
        raise Exception("封面图上传失败", res)


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
        raise Exception("无法解析微信返回内容，可能是编码问题", res.text)

    if 'media_id' in result:
        return result['media_id']
    else:
        raise Exception("草稿上传失败：", json.dumps(result, ensure_ascii=False, indent=2))


def publish_article(access_token, media_id):
    url = f"https://api.weixin.qq.com/cgi-bin/freepublish/submit?access_token={access_token}"
    res = requests.post(url, json={"media_id": media_id}).json()
    if 'publish_id' in res:
        return res['publish_id']
    else:
        raise Exception("发布失败", res)


def get_publish_result(access_token, publish_id):
    url = f"https://api.weixin.qq.com/cgi-bin/freepublish/get?access_token={access_token}"
    res = requests.post(url, json={"publish_id": publish_id}).json()
    return res



TITLE = "2025-06-24.md"


#COVER_IMG_PATH = "cover.png"

# MARKDOWN_PATH is supplied by the caller.






def upload_main(MARKDOWN_PATH, TITLE='Arxiv Daily'):
    from src.config import WECHAT_APPID, WECHAT_SECRET, WECHAT_THUMB_MEDIA_ID, WECHAT_AUTHOR
    appid = WECHAT_APPID
    secret = WECHAT_SECRET
    APPID = appid
    APPSECRET = secret
    AUTHOR = WECHAT_AUTHOR
    DIGEST = "Arxiv Daily"

    access_token = get_access_token(APPID, APPSECRET)
    print("[1] access_token 获取成功")
    thumb_media_id = WECHAT_THUMB_MEDIA_ID
    print("[2] 封面图上传成功：", thumb_media_id)

    with open(MARKDOWN_PATH, 'r', encoding='utf-8') as f:
        md_text = f.read()
    html_text = markdown.markdown(md_text)

    media_id = upload_article_draft(access_token, TITLE, AUTHOR, html_text, DIGEST, thumb_media_id)
    print("[3] 图文草稿上传成功：", media_id)
