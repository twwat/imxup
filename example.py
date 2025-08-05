# Example usage of the imx.to uploader

import os
from imxup import ImxToUploader

# Initialize the uploader
uploader = ImxToUploader()

# Upload a folder of images as a gallery
try:
    # Replace with the path to your image folder
    folder_path = "./test_images"
    
    # Upload the folder as a gallery
    results = uploader.upload_folder(folder_path, gallery_name="Test Gallery")
    
    # Print results
    print("Gallery URL:", results['gallery_url'])
    print("Images uploaded:", len(results['images']))
    
    for i, image_data in enumerate(results['images'], 1):
        print(f"{i}. {image_data['image_url']}")
        
except Exception as e:
    print(f"Error: {e}")