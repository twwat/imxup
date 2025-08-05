import os
import requests
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class ImxToUploader:
    def __init__(self):
        self.api_key = os.getenv('IMX_API')
        if not self.api_key:
            raise ValueError("IMX_API key not found in environment variables")
        
        # Base URL for imx.to API (this might need adjustment based on actual API)
        self.base_url = "https://imx.to/api"
    
    def upload_image(self, image_path):
        """
        Upload a single image to imx.to
        """
        try:
            with open(image_path, 'rb') as f:
                files = {'file': f}
                data = {'key': self.api_key}
                
                response = requests.post(
                    f"{self.base_url}/upload",
                    files=files,
                    data=data
                )
                
                if response.status_code == 200:
                    return response.json()
                else:
                    print(f"Upload failed with status code: {response.status_code}")
                    print(f"Response: {response.text}")
                    return None
        except Exception as e:
            print(f"Error uploading {image_path}: {str(e)}")
            return None
    
    def create_gallery(self, image_urls, gallery_title="My Gallery"):
        """
        Create a gallery with the uploaded images
        """
        try:
            data = {
                'key': self.api_key,
                'title': gallery_title,
                'images': image_urls
            }
            
            response = requests.post(
                f"{self.base_url}/gallery/create",
                json=data
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Gallery creation failed with status code: {response.status_code}")
                print(f"Response: {response.text}")
                return None
        except Exception as e:
            print(f"Error creating gallery: {str(e)}")
            return None
    
    def upload_folder(self, folder_path, gallery_title=None):
        """
        Upload all images in a folder and create a gallery
        """
        if not os.path.exists(folder_path):
            raise ValueError(f"Folder {folder_path} does not exist")
        
        if not gallery_title:
            gallery_title = os.path.basename(folder_path)
        
        # Get all image files in the folder
        image_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp')
        image_files = [f for f in os.listdir(folder_path) 
                      if f.lower().endswith(image_extensions)]
        
        if not image_files:
            print(f"No image files found in {folder_path}")
            return None
        
        print(f"Found {len(image_files)} images to upload")
        
        # Upload each image
        uploaded_images = []
        for image_file in image_files:
            image_path = os.path.join(folder_path, image_file)
            print(f"Uploading {image_file}...")
            
            result = self.upload_image(image_path)
            if result and 'url' in result:
                uploaded_images.append(result['url'])
                print(f"Uploaded {image_file} successfully")
            else:
                print(f"Failed to upload {image_file}")
        
        if not uploaded_images:
            print("No images were successfully uploaded")
            return None
        
        print(f"Successfully uploaded {len(uploaded_images)} images")
        
        # Create gallery
        print("Creating gallery...")
        gallery_result = self.create_gallery(uploaded_images, gallery_title)
        
        if gallery_result:
            print("Gallery created successfully!")
            return gallery_result
        else:
            print("Failed to create gallery")
            return None

if __name__ == "__main__":
    uploader = ImxToUploader()
    
    # Example usage
    folder_path = input("Enter the path to the folder containing images: ")
    gallery_title = input("Enter gallery title (optional, press Enter for folder name): ")
    
    result = uploader.upload_folder(folder_path, gallery_title if gallery_title else None)
    
    if result:
        print(f"Gallery URL: {result.get('gallery_url', 'N/A')}")
    else:
        print("Upload failed")