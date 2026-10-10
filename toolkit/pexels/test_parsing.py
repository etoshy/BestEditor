from pexels_client import PexelsClient

def test_ignores_ads_and_keeps_videos():
    ad={"type":"ad_medium","attributes":{"id":"1","video":"https://media.istockphoto.com/x.mp4"}}
    assert PexelsClient._parse_search_item(ad) is None
    item={"type":"video","attributes":{"id":"2","slug":"dog","title":"Dog","video":{"video_files":[{"quality":"hd","width":1280,"height":720,"link":"https://videos.pexels.com/a.mp4","download_link":"https://www.pexels.com/download/video/2/"}]}}}
    v=PexelsClient._parse_search_item(item)
    assert v and v.id=="2" and v.video_files[0]["download_link"].startswith("https://www.pexels.com/download/")
