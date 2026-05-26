import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options

def test_selenium():
    options = Options()
    # options.add_argument('--headless')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    driver.get("https://www.atacadao.com.br/api/catalog_system/pub/products/search?fq=productClusterIds:312&_from=0&_to=49&sc=1")
    
    time.sleep(5)
    print("Page title:", driver.title)
    print("Page source snippet:", driver.page_source[:500])
    
    driver.quit()

if __name__ == "__main__":
    test_selenium()
