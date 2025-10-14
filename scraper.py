from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import time
import json
import re
from datetime import datetime
import openai
import os
import pytesseract
from PIL import Image
import instaloader
import requests
from io import BytesIO

def format_menu_with_openai(raw_menu_text, restaurant_name):
    """Use OpenAI GPT to format the menu into a clean, readable list with emojis"""
    try:
        # Set up OpenAI client
        client = openai.OpenAI(
            api_key=os.getenv('OPENAI_KEY')
        )
        
        if "ICA" in restaurant_name:
            prompt = f"""
            You are a Swedish restaurant menu formatter. This is a weekly lunch menu from ICA Supermarket Hansa. 
            Extract today's lunch dish based on the current weekday and format it nicely.

            Current weekday: {get_current_weekday()}

            Rules:
            - Find the dish for today's weekday
            - Add appropriate food emojis before each item
            - Keep Swedish names but make them readable
            - One dish per line
            - Remove any extra text like prices, week numbers, etc.

            Raw menu text:
            {raw_menu_text}

            Format as a simple list with emojis for today only.
            """
        else:
            prompt = f"""
            You are a Swedish restaurant menu formatter. Convert this raw Swedish lunch menu text into a clean, emoji-formatted list.

            Rules:
            - Extract only the actual food items/dishes
            - Add appropriate food emojis before each item
            - Keep Swedish names but make them readable
            - One dish per line
            - Remove any extra text like greetings, store info, etc.

            Raw menu text:
            {raw_menu_text}

            Format as a simple list with emojis, like:
            🌺 Hawaiikassler med ris
            🥧 Ost- & skinkpaj
            🐟 Fisksoppa
            """
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "user", "content": prompt}
            ],
            max_tokens=200,
            temperature=0.3
        )
        
        formatted_text = response.choices[0].message.content.strip()
        print(f"✅ OpenAI formatted menu successfully for {restaurant_name}")
        return formatted_text
        
    except Exception as e:
        print(f"❌ OpenAI formatting failed for {restaurant_name}: {e}")
        print("💡 Make sure to set OPENAI_KEY environment variable")
        # Fallback to original text
        return raw_menu_text

def get_current_weekday():
    """Get current weekday in Swedish"""
    weekdays = {
        0: "måndag",
        1: "tisdag", 
        2: "onsdag",
        3: "torsdag",
        4: "fredag",
        5: "lördag",
        6: "söndag"
    }
    return weekdays[datetime.now().weekday()]

def clean_menu_text(text):
    """Clean up menu text by removing UI elements and extra whitespace"""
    # Remove common UI elements
    ui_elements = [
        "All reactions:",
        "from ICA Supermarket Hansa | Malmö",
        "Email or phone number",
        "Password"
    ]
    
    for element in ui_elements:
        text = text.replace(element, "")
    
    # Remove contact information patterns
    text = re.sub(r'\d{3}-\d{2} \d{2} \d{2}', '', text)  # Phone numbers
    text = re.sub(r'[a-zA-Z]+\.[a-zA-Z]+@[a-zA-Z]+\.[a-zA-Z]+', '', text)  # Email addresses
    text = re.sub(r'[a-zA-Z]+\.[a-zA-Z]+/[a-zA-Z]+', '', text)  # Website URLs
    
    # Clean up extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

def is_swedish_text(line: str) -> bool:
    """Heuristically determine if a line is Swedish (and not French).

    - Exclude lines containing common French accented characters
    - Prefer lines containing Swedish letters or common Swedish words
    - Exclude obvious non-content like prices/week numbers
    """
    if not line:
        return False

    lowered = line.lower().strip()

    # Exclude French accented characters
    french_accents = "éèêàâîïôûùçœ“”’ºº»«"
    if any(ch in lowered for ch in french_accents):
        return False

    # Exclude obvious noise
    if re.search(r"\bvecka\b|v\.\d+|\d+\s*:-|\d+kr|\bsek\b", lowered):
        return False

    # Require at least some Swedish characteristics
    swedish_letters = any(ch in line for ch in "åäöÅÄÖ")
    swedish_words = any(word in lowered for word in [
        "med", "och", "sås", "potatis", "lök", "grädde", "kyckling",
        "lax", "fläsk", "nöt", "grönsaker", "ris", "gratäng", "pasta",
        "gryta", "sallad", "dagens", "vegetar", "wallenbergare"
    ])

    return swedish_letters or swedish_words

def extract_text_from_images(driver):
    """Extract text from images on the page using OCR"""
    try:
        # Find all images on the page
        images = driver.find_elements(By.TAG_NAME, "img")
        extracted_texts = []
        
        for i, img in enumerate(images):
            try:
                # Get image source
                img_src = img.get_attribute("src")
                if not img_src or "data:" in img_src:
                    continue
                
                print(f"Processing image {i+1}: {img_src[:100]}...")
                
                # Download image
                response = requests.get(img_src, timeout=10)
                if response.status_code == 200:
                    # Open image with PIL
                    image = Image.open(BytesIO(response.content))
                    
                    # Extract text using OCR with better settings
                    # Try multiple OCR configurations for better accuracy
                    configs = [
                        '--psm 6',  # Uniform block of text
                        '--psm 4',  # Single column of text
                        '--psm 3'   # Default
                    ]
                    
                    best_text = ""
                    for config in configs:
                        try:
                            text = pytesseract.image_to_string(image, lang='swe', config=config)
                            if len(text.strip()) > len(best_text.strip()):
                                best_text = text
                        except:
                            continue
                    
                    print(f"OCR extracted from image {i+1}: {best_text[:100]}...")
                    
                    # Look for menu content with broader criteria
                    if len(best_text.strip()) > 20 and any(word in best_text.lower() for word in ["lunch", "måndag", "tisdag", "onsdag", "torsdag", "fredag", "veck", "meny"]):
                        extracted_texts.append(best_text.strip())
                        print(f"✅ Extracted menu text from image {i+1}")
                        
            except Exception as e:
                print(f"❌ Failed to process image {i+1}: {e}")
                continue
        
        return "\n\n".join(extracted_texts) if extracted_texts else None
        
    except Exception as e:
        print(f"❌ OCR extraction failed: {e}")
        return None

def _ocr_image_bytes(image_bytes: bytes) -> str:
    """Run OCR on raw image bytes using Tesseract Swedish language, trying multiple configs."""
    try:
        image = Image.open(BytesIO(image_bytes)).convert('RGB')
        # Upscale small images to help OCR
        if image.width < 300 or image.height < 300:
            image = image.resize((image.width * 2, image.height * 2))

        configs = ['--psm 6', '--psm 4', '--psm 3']
        best_text = ""
        for config in configs:
            try:
                text = pytesseract.image_to_string(image, lang='swe', config=config)
                if len(text.strip()) > len(best_text.strip()):
                    best_text = text
            except Exception:
                continue
        return best_text.strip()
    except Exception as e:
        print(f"❌ OCR bytes processing failed: {e}")
        return ""

def scrape_ica_instaloader(username: str = "ica_supermarket_hansa", max_posts: int = 10):
    """Fetch recent Instagram posts via Instaloader (no login) and OCR for weekly menu text."""
    try:
        print(f"Loading ICA via Instaloader: https://www.instagram.com/{username}/ ...")
        loader = instaloader.Instaloader(download_pictures=False,
                                         download_videos=False,
                                         download_video_thumbnails=False,
                                         save_metadata=False,
                                         compress_json=False,
                                         quiet=True)

        # Optional login to reduce rate limiting and increase reliability
        ig_user = os.getenv("INSTAGRAM_USERNAME")
        ig_pass = os.getenv("INSTAGRAM_PASSWORD")
        if ig_user and ig_pass:
            try:
                print("Attempting Instagram login via Instaloader...")
                loader.login(ig_user, ig_pass)
                print("✅ Instagram login successful")
            except Exception as e:
                print(f"⚠️ Instagram login failed, continuing without login: {e}")

        profile = instaloader.Profile.from_username(loader.context, username)
        count_checked = 0
        for post in profile.get_posts():
            if count_checked >= max_posts:
                break
            count_checked += 1
            try:
                url = post.url  # direct image URL
                print(f"Processing IG post {count_checked}: {url[:80]}...")
                resp = requests.get(url, timeout=15)
                if resp.status_code != 200:
                    continue
                text = _ocr_image_bytes(resp.content)
                print(f"OCR result {count_checked}: {text[:120]}...")
                if len(text) > 30 and any(word in text.lower() for word in [
                    "veckomeny", "veckans", "måndag", "tisdag", "onsdag", "torsdag", "fredag", "lunch"
                ]):
                    cleaned = clean_menu_text(text)
                    print("✅ Found weekly menu content via Instaloader")
                    return cleaned
            except Exception as e:
                print(f"❌ Failed to process IG post {count_checked}: {e}")
                continue
        print("❌ No weekly menu content found via Instaloader")
        return None
    except Exception as e:
        print(f"❌ Instaloader failed: {e}")
        return None

def scrape_ica_instagram(page_name, url):
    """Scrape ICA Instagram page for weekly menu using improved OCR"""
    # Set up headless Chrome with better settings for Instagram
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=chrome_options)
    
    try:
        # Try Instagram page instead of Facebook
        instagram_url = "https://www.instagram.com/ica_supermarket_hansa/"
        print(f"Loading {page_name} Instagram: {instagram_url}...")
        driver.get(instagram_url)
        
        # Wait for page to load
        time.sleep(8)
        
        # Look for recent posts (weekly menu posted on Mondays)
        try:
            # Find post images - Instagram uses different selectors
            posts = driver.find_elements(By.CSS_SELECTOR, "article img")
            if not posts:
                posts = driver.find_elements(By.TAG_NAME, "img")
            
            print(f"Found {len(posts)} potential images")
            
            # Focus on the first few recent posts
            for i, img in enumerate(posts[:8]):  # Only check first 8 images
                try:
                    img_src = img.get_attribute("src")
                    if not img_src or "data:" in img_src or len(img_src) < 50:
                        continue
                    
                    print(f"Processing Instagram image {i+1}: {img_src[:80]}...")
                    
                    # Download and process image
                    response = requests.get(img_src, timeout=15)
                    if response.status_code == 200:
                        image = Image.open(BytesIO(response.content))
                        
                        # Improve image for OCR
                        image = image.convert('RGB')
                        # Resize if too small
                        if image.width < 300 or image.height < 300:
                            image = image.resize((image.width * 2, image.height * 2))
                        
                        # Try OCR with Swedish language
                        text = pytesseract.image_to_string(image, lang='swe', config='--psm 6')
                        
                        print(f"OCR result {i+1}: {text[:100]}...")
                        
                        # Look for weekly menu content
                        if len(text.strip()) > 30 and any(word in text.lower() for word in ["veckomeny", "måndag", "tisdag", "onsdag", "torsdag", "fredag", "lunch"]):
                            cleaned_content = clean_menu_text(text)
                            print(f"✅ Found weekly menu content from Instagram image {i+1}")
                            return cleaned_content
                            
                except Exception as e:
                    print(f"❌ Failed to process Instagram image {i+1}: {e}")
                    continue
            
            print(f"❌ No weekly menu content found on Instagram for {page_name}")
            return None
            
        except Exception as e:
            print(f"❌ Error finding Instagram posts: {e}")
            return None
            
    except Exception as e:
        print(f"Error scraping {page_name} Instagram: {e}")
        return None
    finally:
        driver.quit()

def scrape_la_gare_menu():
    """Scrape La Gare's lunch menu for today"""
    # Set up headless Chrome
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=chrome_options)
    
    try:
        url = "https://ligula.se/sv/restauranger/la-gare-malmo/la-gare-garden-lunch/"
        print(f"Loading La Gare menu: {url}...")
        driver.get(url)
        
        # Wait for page to load
        time.sleep(5)
        
        # Accept cookies if present
        try:
            cookie_button = driver.find_element(By.XPATH, "//button[contains(text(), 'OK') or contains(text(), 'Acceptera')]")
            cookie_button.click()
            time.sleep(2)
            print("✅ Accepted cookies")
        except:
            print("ℹ️ No cookie banner found or already accepted")
        
        # Get all text content from the page
        page_text = driver.find_element(By.TAG_NAME, "body").text
        
        # Split into lines
        lines = page_text.split('\n')
        
        # Debug: print some lines to see what we're getting (commented out for performance)
        # print("\n--- First 20 lines from La Gare ---")
        # for i, line in enumerate(lines[:20]):
        #     print(f"{i}: {line}")
        # print("--- End debug lines ---\n")
        
        # Get current weekday (Swedish)
        today = get_current_weekday()
        print(f"Looking for menu for: {today}")
        
        # Find today's menu
        menu_content = []

        # Locate today's section (relaxed match)
        today_index = -1
        for i, line in enumerate(lines):
            normalized = line.strip().lower()
            if today in normalized:
                today_index = i
                print(f"Found today's section: {line}")
                break

        # Extract dishes below today's header until next weekday
        if today_index >= 0:
            for j in range(today_index + 1, min(today_index + 12, len(lines))):
                next_line = lines[j].strip()
                if not next_line:
                    continue
                # Stop if we hit another weekday header
                if any(day in next_line.lower() for day in ["måndag", "tisdag", "onsdag", "torsdag", "fredag"]):
                    break
                # Only keep lines that look Swedish and like dishes
                if len(next_line) > 8 and is_swedish_text(next_line):
                    menu_content.append(next_line)
                    print(f"Added Swedish dish: {next_line}")

        # Also try to find vegetarian option anywhere
        if not any("vegetar" in x.lower() or "veg" in x.lower() for x in menu_content):
            for i, line in enumerate(lines):
                if any(key in line.lower() for key in ["dagens veg", "vegetar", "veg."]):
                    # Look the next few lines for the description
                    for j in range(i + 1, min(i + 6, len(lines))):
                        veg_line = lines[j].strip()
                        if len(veg_line) > 8 and is_swedish_text(veg_line):
                            menu_content.append(f"Vegetarisk: {veg_line}")
                            print(f"Added vegetarian dish: {veg_line}")
                            break
                    break
        
        if menu_content:
            full_menu = "\n".join(menu_content)
            print(f"✅ Found menu for {today}")
            return full_menu
        else:
            print(f"❌ No menu found for {today}")
            return None
            
    except Exception as e:
        print(f"Error scraping La Gare menu: {e}")
        return None
    finally:
        driver.quit()

def scrape_all_restaurants():
    """Scrape all restaurant pages and save to JSON"""
    restaurants = {
        "La Gare Malmö": "scrape_la_gare",
        "ICA Supermarket Hansa": "https://www.instagram.com/ica_supermarket_hansa/"
    }
    
    menu_data = {}
    
    for restaurant_name, url in restaurants.items():
        if restaurant_name == "La Gare Malmö":
            content = scrape_la_gare_menu()
        elif restaurant_name == "ICA Supermarket Hansa":
            # Try Instaloader first; fallback to Selenium if needed
            content = scrape_ica_instaloader()
            if not content:
                content = scrape_ica_instagram(restaurant_name, url)
            
        if content:
            formatted_content = format_menu_with_openai(content, restaurant_name)
            menu_data[restaurant_name] = {
                "raw": content,
                "formatted": formatted_content
            }
    
    # Save to JSON file
    output_file = "menu.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(menu_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n📄 Menu saved to {output_file}")
    print("\nMenu content:")
    for restaurant, data in menu_data.items():
        print(f"\n{restaurant}:")
        print(f"  Raw: {data['raw']}")
        print(f"  Formatted: {data['formatted']}")

if __name__ == "__main__":
    scrape_all_restaurants()