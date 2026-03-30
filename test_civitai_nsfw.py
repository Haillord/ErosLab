# -*- coding: utf-8 -*-
"""
Test script for checking nsfwLevel from CivitAI API
Insert your CIVITAI_API_KEY and run the script
"""

import requests
import os
import sys

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# ==================== SETTINGS ====================
# Insert your API key here or via environment variable
CIVITAI_API_KEY = "d8316cef8ff5561466dc167b26fa64f7"

if not CIVITAI_API_KEY:
    print("WARNING: Insert CIVITAI_API_KEY in code or set environment variable!")
    exit(1)

# ==================== API REQUEST ====================
def test_civitai_nsfw_levels():
    """Test nsfwLevel for different posts"""
    
    url = "https://civitai.com/api/v1/images"
    headers = {"Authorization": f"Bearer {CIVITAI_API_KEY}"}
    
    # Test parameters - request only pornographic content (X rating)
    # Note: XXX is not a valid API parameter, use X and filter by nsfwLevel >= 4
    test_params = [
        {"limit": 20, "nsfw": "X", "sort": "Most Reactions", "period": "Day"},
        {"limit": 20, "nsfw": "X", "sort": "Newest", "period": "Day"},
    ]
    
    print("=" * 80)
    print("TEST NSFWLEVEL FROM CIVITAI API")
    print("=" * 80)
    
    for i, params in enumerate(test_params, 1):
        print(f"\nTEST {i}: nsfw={params['nsfw']}, sort={params['sort']}, period={params['period']}")
        print("-" * 80)
        
        try:
            response = requests.get(url, params=params, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            items = data.get("items", [])
            
            print(f"Got {len(items)} posts")
            
            if not items:
                print("No posts for this request")
                continue
            
            # Analyze first 5 posts
            for idx, item in enumerate(items[:5], 1):
                item_id = item.get("id")
                nsfw_level = item.get("nsfwLevel")
                image_url = item.get("url", "")
                meta = item.get("meta", {})
                prompt = meta.get("prompt", "")[:50] if meta else ""
                
                # Determine rating by nsfwLevel (can be int or string)
                if isinstance(nsfw_level, int):
                    if nsfw_level == 1:
                        rating = "Safe"
                    elif nsfw_level == 2:
                        rating = "Soft NSFW"
                    elif nsfw_level == 3:
                        rating = "Mature"
                    elif nsfw_level == 4:
                        rating = "X"
                    elif nsfw_level == 5:
                        rating = "XXX"
                    else:
                        rating = f"Unknown ({nsfw_level})"
                elif isinstance(nsfw_level, str):
                    rating = nsfw_level  # Already a string like "X", "Mature", etc.
                else:
                    rating = "None (no nsfwLevel)"
                
                print(f"\n  Post #{idx}:")
                print(f"    ID: {item_id}")
                print(f"    nsfwLevel: {nsfw_level} -> {rating}")
                print(f"    URL: {image_url}")  # Full URL
                if prompt:
                    print(f"    Prompt: {prompt}...")
                
        except Exception as e:
            print(f"Error: {e}")
    
    print("\n" + "=" * 80)
    print("STATISTICS:")
    print("=" * 80)
    
    # Collect general statistics
    all_items = []
    for params in test_params:
        try:
            response = requests.get(url, params=params, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                all_items.extend(data.get("items", []))
        except:
            pass
    
    nsfw_counts = {}
    for item in all_items:
        level = item.get("nsfwLevel", "unknown")
        nsfw_counts[level] = nsfw_counts.get(level, 0) + 1
    
    print(f"\nTotal posts analyzed: {len(all_items)}")
    print("\nnsfwLevel distribution:")
    for level, count in sorted(nsfw_counts.items()):
        if level is None:
            rating = "None"
        elif isinstance(level, int):
            if level == 1:
                rating = "Safe"
            elif level == 2:
                rating = "Soft NSFW"
            elif level == 3:
                rating = "Mature"
            elif level == 4:
                rating = "X"
            elif level == 5:
                rating = "XXX"
            else:
                rating = f"Unknown"
        else:
            rating = str(level)  # Already a string like "X", "Mature", etc.
        print(f"  nsfwLevel {level} ({rating}): {count} posts ({count/len(all_items)*100:.1f}%)")
    
    print("\n" + "=" * 80)
    print("RECOMMENDATIONS:")
    print("=" * 80)
    
    # Analyze which nsfwLevel are most common
    max_count = max(nsfw_counts.values()) if nsfw_counts else 0
    most_common_levels = [level for level, count in nsfw_counts.items() if count == max_count]
    
    if most_common_levels:
        print(f"\nMost common nsfwLevel: {most_common_levels}")
        print("\nRecommendations for bot filter (porn only):")
        
        # Check for X or XXX content (string comparison)
        has_x = any(str(level).upper() in ["X", "XXX"] for level in most_common_levels)
        has_mature = any(str(level).lower() == "mature" for level in most_common_levels)
        
        if has_x:
            print("[OK] nsfwLevel = X or XXX - suitable for X/XXX (porn) content only")
            print("     Filter: if nsfw_level in ['X', 'XXX'] or nsfw_level >= 4")
        elif has_mature:
            print("[WARN] Found Mature content - filter it out for porn-only mode")
            print("       Filter: if nsfw_level in ['X', 'XXX'] or nsfw_level >= 4")
        else:
            print("[FAIL] No X/XXX content found")
            print("       Try other request parameters or check API access")

if __name__ == "__main__":
    test_civitai_nsfw_levels()
