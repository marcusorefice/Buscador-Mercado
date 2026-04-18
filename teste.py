import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By

def inspecionar_site():
    url = "https://www.assai.com.br/ofertas/sao-paulo/assai-jundiai"
    print(f"📡 Iniciando inspeção em: {url}")

    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        driver.get(url)
        print("⏳ Aguardando 10 segundos para carregamento completo...")
        time.sleep(10)

        # 1. Capturar Print da Tela (O que o robô vê)
        driver.save_screenshot("visao_do_robo.png")
        print("📸 Screenshot salvo como 'visao_do_robo.png'. Abra este arquivo para ver a página.")

        # 2. Listar todos os links de Encarte (data-fancybox)
        print("\n🔎 Buscando links de encartes (padrão fancybox):")
        links_encarte = driver.find_elements(By.CSS_SELECTOR, 'a[data-fancybox="ofertas"]')
        if not links_encarte:
            print("❌ Nenhum link com data-fancybox='ofertas' encontrado.")
        for idx, link in enumerate(links_encarte):
            href = link.get_attribute('href')
            print(f"   [{idx+1}] Link: {href}")

        # 3. Listar todas as imagens da página
        print("\n🖼️ Listando todas as imagens (<img>) detectadas:")
        todas_imgs = driver.find_elements(By.TAG_NAME, 'img')
        for idx, img in enumerate(todas_imgs[:15]): # Limitado as 15 primeiras
            src = img.get_attribute('src')
            alt = img.get_attribute('alt')
            print(f"   [{idx+1}] Alt: {alt} | Src: {src}")

        # 4. Verificar mensagem de "Sem Encarte"
        print("\n⚠️ Verificando mensagens de status:")
        possiveis_avisos = driver.find_elements(By.CSS_SELECTOR, ".ofertas-tab-validade, .msg-vazio, .no-results")
        for aviso in possiveis_avisos:
            if aviso.is_displayed():
                print(f"   🚩 AVISO VISÍVEL: {aviso.text.strip()}")

    finally:
        driver.quit()
        print("\n✅ Inspeção finalizada.")

if __name__ == "__main__":
    inspecionar_site()