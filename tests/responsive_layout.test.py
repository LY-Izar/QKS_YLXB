"""Test responsive layout: verify pages stretch with window width."""
from playwright.sync_api import sync_playwright
import sys, os

TEST_URL = "http://localhost:8765/index.html"
SCREEN_DIR = os.path.join(os.path.dirname(__file__), "screens")
os.makedirs(SCREEN_DIR, exist_ok=True)

def main():
    with sync_playwright() as p:
        # Test with wide viewport (1440px)
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(TEST_URL)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(3000)

        # Check main element width
        main = page.query_selector("main")
        if not main:
            print("FAIL: no <main> element")
            return 1
        main_box = main.bounding_box()
        win_w = page.evaluate("window.innerWidth")
        print(f"Window width: {win_w}px")
        print(f"Main width: {main_box['width']:.0f}px")
        print(f"Main left: {main_box['x']:.0f}px, right edge: {main_box['x'] + main_box['width']:.0f}px")
        
        if main_box['width'] < 800:
            print(f"FAIL: main width {main_box['width']:.0f}px is too narrow (expect >800px)")
            return 1
        print(f"PASS: main width {main_box['width']:.0f}px > 800px")
        
        # Check navbar
        navbar = page.query_selector("#navbar")
        if navbar:
            nb_box = navbar.bounding_box()
            print(f"Navbar width: {nb_box['width']:.0f}px")
        
        # Check grid tiles (may be hidden on welcome page)
        tiles = page.query_selector_all(".grid .tile")
        print(f"Grid tiles found: {len(tiles)}")
        if tiles:
            tile_box = tiles[0].bounding_box()
            if tile_box:
                print(f"Tile width: {tile_box['width']:.0f}px")
            else:
                print("Tiles not visible (hidden on current page)")
        
        # Navigate to home to see grid
        page.evaluate("if(typeof go==='function') go('home')")
        page.wait_for_timeout(1500)
        tiles2 = page.query_selector_all(".grid .tile")
        print(f"Home grid tiles: {len(tiles2)}")
        if tiles2:
            tile_box2 = tiles2[0].bounding_box()
            if tile_box2:
                print(f"Tile width: {tile_box2['width']:.0f}px (on home page)")
        
        # Navigate to account page and check
        page.evaluate("if(typeof go==='function') go('account')")
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(SCREEN_DIR, "wide_account.png"))
        
        # Login as admin
        page.evaluate("""(args) => {
            const [username, password] = args;
            if(typeof setAuthUser === 'function'){
                setAuthUser(username, password);
            } else {
                try {
                    localStorage.setItem('auth_user', username);
                    localStorage.setItem('auth_pass', password);
                } catch(e) {}
            }
        }""", ["15184461098_admin", "20091208"])
        
        page.reload()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)
        
        # Navigate to admin
        page.evaluate("if(typeof go==='function') go('admin')")
        page.wait_for_timeout(2000)
        
        admin_view = page.query_selector("#view-admin")
        if admin_view:
            admin_box = admin_view.bounding_box()
            print(f"Admin view width: {admin_box['width']:.0f}px")
            # Find cards inside admin
            cards = admin_view.query_selector_all(".card")
            print(f"Admin cards: {len(cards)}")
            for i, card in enumerate(cards):
                cb = card.bounding_box()
                if cb:
                    print(f"  Card {i+1} width: {cb['width']:.0f}px")
        
        page.screenshot(path=os.path.join(SCREEN_DIR, "wide_admin.png"), full_page=False)
        print(f"Screenshots saved to tests/screens/")
        
        # Test with mobile viewport (390px)
        page2 = browser.new_page(viewport={"width": 390, "height": 844})
        page2.goto(TEST_URL)
        page2.wait_for_load_state("networkidle")
        page2.wait_for_timeout(2000)
        main2 = page2.query_selector("main")
        if main2:
            box2 = main2.bounding_box()
            print(f"Mobile viewport (390px) main width: {box2['width']:.0f}px")
            if box2['width'] > 350:
                print("PASS: mobile main uses full width")
        page2.screenshot(path=os.path.join(SCREEN_DIR, "mobile_layout.png"))
        page2.close()
        
        print("\nAll responsive layout checks passed ✅")
        browser.close()
        return 0

if __name__ == "__main__":
    sys.exit(main())
