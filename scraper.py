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

def get_weekday_sequence():
    """Return list of Swedish weekdays (Mon-Fri) in order, lowercase."""
    return [
        "måndag",
        "tisdag",
        "onsdag",
        "torsdag",
        "fredag"
    ]

def _emoji_for_line(text: str) -> str:
    """Choose an emoji based on dish keywords."""
    t = text.lower()
    mapping = [
        (['lax', 'fisk', 'torsk', 'sill', 'räkor', 'sill'], '🐟'),
        (['kyckling', 'kyckl'], '🍗'),
        (['köttbullar', 'fläsk', 'nöt', 'biff', 'ox', 'wallenbergare'], '🥩'),
        (['pasta', 'tortellini', 'lasagne', 'lasagna'], '🍝'),
        (['sallad', 'ceasar', 'caesar'], '🥗'),
        (['soppa'], '🥣'),
        (['vegetar', 'vegansk', 'veg'], '🥦'),
        (['paj', 'quiche'], '🥧'),
        (['ris'], '🍚'),
        (['potatis', 'mos'], '🥔'),
        (['gryta', 'gryt'], '🍲'),
        (['burgare', 'burger'], '🍔'),
        (['kebab', 'falafel'], '🥙'),
    ]
    for keys, emoji in mapping:
        if any(k in t for k in keys):
            return emoji
    return '🍽️'

def _format_lines_with_emojis(lines: list[str]) -> str:
    return "\n".join([f"{_emoji_for_line(ln)} {ln}" for ln in lines])

def extract_week_from_text(raw_text: str) -> dict:
    """Parse a Swedish weekly menu text into a dict of weekdays -> list of dish lines.

    Heuristic approach using weekday headers; tolerant to punctuation and casing.
    """
    if not raw_text:
        return {}

    text = raw_text.replace("\r", "\n")
    # Normalize some common OCR separators into newlines to ease splitting
    text = re.sub(r"\s*\|\s*", "\n", text)
    text = re.sub(r"\s{2,}", " ", text)

    days = get_weekday_sequence()
    # Build regex to find day headers case-insensitively
    day_pattern = r"(?i)(måndag|tisdag|onsdag|torsdag|fredag)\b"

    # Find day occurrences across the whole text
    matches = list(re.finditer(day_pattern, text))
    if not matches:
        # Fallback: try lines based approach (legacy)
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        day_to_index = {}
        for i, line in enumerate(lines):
            lowered = line.lower()
            for day in days:
                if re.search(rf"\b{day}\b\s*[:\-]?", lowered):
                    day_to_index.setdefault(day, i)
        ordered = [(day, day_to_index[day]) for day in days if day in day_to_index]
        ordered.sort(key=lambda x: x[1])
        week = {}
        for idx, (day, start) in enumerate(ordered):
            end = ordered[idx + 1][1] if idx + 1 < len(ordered) else len(lines)
            dishes = []
            for j in range(start + 1, end):
                ln = lines[j].strip()
                if not ln:
                    continue
                if any(re.search(rf"\b{d}\b", ln.lower()) for d in days):
                    break
                if len(ln) > 6 and is_swedish_text(ln):
                    dishes.append(ln)
            if dishes:
                week[day] = dishes
        return week

    # Build per-day segments from positions
    week = {}
    for i, m in enumerate(matches):
        day_raw = m.group(1)
        day = day_raw.lower()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        segment = text[start:end].strip()
        # Split segment on common delimiters into potential dishes
        parts = re.split(r"\s*[\n\.|•|-]\s+", segment)
        dishes = []
        for p in parts:
            s = p.strip(" -\n\t:|·")
            if len(s) < 6:
                continue
            if is_swedish_text(s):
                dishes.append(s)
        if dishes:
            week[day] = dishes

    return week

def format_week_with_openai(week_map: dict, restaurant_name: str) -> dict:
    """Format each day's dishes with emojis using OpenAI; fallback to prefix if API fails."""
    formatted = {}
    try:
        client = openai.OpenAI(api_key=os.getenv('OPENAI_KEY'))
        # Build a compact prompt asking for same order back
        plain = []
        for day in get_weekday_sequence():
            items = week_map.get(day, [])
            if not items:
                continue
            plain.append(f"{day.capitalize()}:\n" + "\n".join(items))
        if not plain:
            return formatted
        prompt = (
            "Du är en formatterare för svenska lunchmenyer. Lägg till passande mat-emojis i början av varje rad. "
            "Behåll dagarnas ordning och rubriker. Returnera EXAKT samma struktur i textform, inte JSON.\n\n" +
            "\n\n".join(plain)
        )
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600,
            temperature=0.2
        )
        out = response.choices[0].message.content.strip()
        # Parse back into per day sections
        sections = re.split(r"(?mi)^(Måndag|Tisdag|Onsdag|Torsdag|Fredag)\s*:\s*$", out)
        # sections alternates: [prefix, Day, content, Day, content, ...]
        tmp_day = None
        for part in sections:
            if not part:
                continue
            low = part.lower()
            if low in get_weekday_sequence():
                tmp_day = low
                continue
            if tmp_day:
                formatted[tmp_day] = part.strip()
                tmp_day = None
        # Fallback fill any missing days with simple emoji bullets
        for day in week_map:
            if day not in formatted:
                formatted[day] = _format_lines_with_emojis(week_map[day])
        return formatted
    except Exception:
        # Local emoji-based fallback
        for day, items in week_map.items():
            formatted[day] = _format_lines_with_emojis(items)
        return formatted

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

# Instaloader path removed; using Selenium + OCR approach only

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
    """Scrape La Gare's lunch menu for the whole week (Mon-Fri)."""
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
        
        # Build weekly map by scanning for weekday headers
        days = get_weekday_sequence()
        day_indices = {}
        for i, line in enumerate(lines):
            lowered = line.strip().lower()
            for day in days:
                if re.search(rf"\b{day}\b", lowered) and day not in day_indices:
                    day_indices[day] = i
        ordered = [(d, day_indices[d]) for d in days if d in day_indices]
        ordered.sort(key=lambda x: x[1])

        # Exclude obvious footer/noise content
        exclude_keywords = [
            "restaurang la gare", "hållbarhet", "våra hotell", "bli medlem", "företagsavtal",
            "idrottslag", "användarvillkor", "sekretesspolicy", "bedrägeri", "omdömen",
            "varmt välkommen", "fråga personalen"
        ]

        def is_noise(ln: str) -> bool:
            low = ln.lower()
            return any(k in low for k in exclude_keywords)

        week_map = {}
        for idx, (day, start) in enumerate(ordered):
            end = ordered[idx + 1][1] if idx + 1 < len(ordered) else len(lines)
            bucket = []
            for j in range(start + 1, end):
                ln = lines[j].strip()
                if not ln:
                    continue
                if any(d in ln.lower() for d in days):
                    break
                if is_noise(ln):
                    continue
                if len(ln) > 8 and is_swedish_text(ln):
                    bucket.append(ln)
                # Safety cap per day to avoid swallowing the whole page footer
                if len(bucket) >= 6:
                    break
            # Try to enrich vegetarian option if missing
            if not any("vegetar" in x.lower() or "veg" in x.lower() for x in bucket):
                for i, line in enumerate(lines):
                    if any(key in line.lower() for key in ["dagens veg", "vegetar", "veg."]):
                        for j in range(i + 1, min(i + 6, len(lines))):
                            veg_line = lines[j].strip()
                            if is_noise(veg_line):
                                continue
                            if len(veg_line) > 8 and is_swedish_text(veg_line):
                                bucket.append(f"Vegetarisk: {veg_line}")
                                break
                        break
            if bucket:
                week_map[day] = bucket

        if week_map:
            print("✅ Found La Gare weekly menu")
            return week_map
        print("❌ No weekly menu found for La Gare")
        return None
            
    except Exception as e:
        print(f"Error scraping La Gare menu: {e}")
        return None
    finally:
        driver.quit()

def scrape_all_restaurants():
    """Scrape all restaurants and save the full week's menus in one go.

    Output structure per restaurant:
    {
      "week_raw_text": "..." (optional),
      "week": { "måndag": {"raw": [..], "formatted": ".."}, ... },
      "formatted_today": "..."  # For backward compatibility
    }
    """
    restaurants = {
        "La Gare Malmö": "scrape_la_gare",
        "ICA Supermarket Hansa": "https://www.instagram.com/ica_supermarket_hansa/"
    }
    
    menu_data = {}
    
    for restaurant_name, url in restaurants.items():
        if restaurant_name == "La Gare Malmö":
            week_map = scrape_la_gare_menu()
            week_raw_text = None
        elif restaurant_name == "ICA Supermarket Hansa":
            # Use Selenium+OCR for Instagram weekly menu text
            week_raw_text = scrape_ica_instagram(restaurant_name, url)
            week_map = extract_week_from_text(week_raw_text) if week_raw_text else None
        else:
            week_map = None
            week_raw_text = None
        
        if week_map:
            formatted_week = format_week_with_openai(week_map, restaurant_name)
            # Build per-day objects
            week_obj = {}
            for day in get_weekday_sequence():
                items = week_map.get(day)
                if not items:
                    continue
                week_obj[day] = {
                    "raw": items,
                    "formatted": formatted_week.get(day, _format_lines_with_emojis(items))
                }
            today_key = get_current_weekday()
            formatted_today = week_obj.get(today_key, {}).get("formatted")
            menu_data[restaurant_name] = {
                **({"week_raw_text": week_raw_text} if week_raw_text else {}),
                "week": week_obj,
                "formatted_today": formatted_today or "",
                # Backward compatibility with existing Slack workflow
                "formatted": formatted_today or ""
            }
        elif week_raw_text:
            # Fallback: include restaurant with today's formatted text even if per-day parsing failed
            today_formatted = format_menu_with_openai(week_raw_text, restaurant_name)
            menu_data[restaurant_name] = {
                "week_raw_text": week_raw_text,
                "week": {},
                "formatted_today": today_formatted,
                "formatted": today_formatted
            }
    
    # Save to JSON file
    output_file = "menu.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(menu_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n📄 Weekly menus saved to {output_file}")
    for restaurant, data in menu_data.items():
        print(f"- {restaurant}: days captured = {len(data.get('week', {}))}")

if __name__ == "__main__":
    scrape_all_restaurants()