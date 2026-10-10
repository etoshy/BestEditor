from magnific_client import MagnificClient

def test_build_search_url():
    c = MagnificClient.__new__(MagnificClient)
    url = c.build_search_url("dog")
    assert "query=dog" in url and "type=video" in url

if __name__ == "__main__":
    test_build_search_url(); print("OK")
