import os
import logging
import base64
from pathlib import Path
from PIL import Image, ImageEnhance, ImageFilter
from pdf2image import convert_from_path
import subprocess

logger = logging.getLogger("DocumentOptimizer")

class DocumentOptimizer:
    def __init__(self, dpi=400, resize_max=3072):
        self.dpi = dpi
        self.resize_max = resize_max

    def optimize_image(self, img_path: Path, inplace=False) -> str:
        """
        Optimiert ein Bild für OCR/Archivierung.
        Returns: Base64 String des Bildes (für AI-Analyse).
        Wenn inplace=True: Das Bild auf der Festplatte wird durch die optimierte Version (JPEG high quality) ersetzt.
        """
        try:
            with Image.open(img_path) as img:
                # 1. Graustufen
                img = img.convert('L')
                
                # 2. Resize (High Res)
                if max(img.size) > self.resize_max:
                    img.thumbnail((self.resize_max, self.resize_max), Image.Resampling.BICUBIC)
                
                # 3. Intelligentes Schärfen
                img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))
                
                # 4. Moderater Kontrast
                img = ImageEnhance.Contrast(img).enhance(1.5)
                
                # 5. PNG für Base64 (Verlustfrei für AI)
                png_path = str(img_path).replace(".jpg", ".png")
                img.save(png_path, "PNG")
                
                with open(png_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode('utf-8')
                
                os.remove(png_path)
                
                if inplace:
                    # 6. JPEG speichern (für PDF Rebuild)
                    img.save(img_path, "JPEG", quality=85)
                
                return b64
        except Exception as e:
            logger.error(f"Error optimizing image {img_path}: {e}")
            return ""

    def create_archival_pdf(self, input_pdf: Path, output_pdf: Path, sidecar_text: str = None):
        """
        Erstellt ein PDF/A aus dem Input-PDF mit optimierten Bildern und OCR-Layer.
        """
        work_dir = input_pdf.parent / f"optimize_{input_pdf.stem}_{os.getpid()}"
        work_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            # 1. PDF -> Bilder
            img_dir = work_dir / "imgs"
            img_dir.mkdir(exist_ok=True)
            
            image_paths = convert_from_path(str(input_pdf), dpi=self.dpi, output_folder=str(img_dir), fmt='jpeg', paths_only=True)
            image_paths.sort()
            
            optimized_images = []
            
            # 2. Bilder optimieren
            for p in image_paths:
                p_path = Path(p)
                self.optimize_image(p_path, inplace=True) # Optimiert Bild in-place für das Archiv-PDF, da das Original NICHT angefasst wird
                optimized_images.append(p_path)
            
            # 3. Rebuild PDF
            rebuilt_pdf = work_dir / "rebuilt.pdf"
            if optimized_images:
                img_objs = [Image.open(p) for p in optimized_images]
                img_objs[0].save(str(rebuilt_pdf), save_all=True, append_images=img_objs[1:], resolution=self.dpi)
            
            # 4. OCRmyPDF
            cmd = [
                "ocrmypdf",
                "--output-type", "pdfa",
                "--deskew",
                "--optimize", "1", # Balance zwischen Größe und Qualität
                "-l", "deu+eng",
            ]
            
            if sidecar_text:
                sidecar_path = work_dir / "sidecar.txt"
                sidecar_path.write_text(sidecar_text, encoding="utf-8")
                cmd.extend(["--sidecar", str(sidecar_path), "--skip-text"])
            else:
                cmd.append("--force-ocr")
                
            cmd.extend([str(rebuilt_pdf), str(output_pdf)])
            
            logger.info(f"Running OCRmyPDF: {' '.join(cmd)}")
            subprocess.run(cmd, check=True, capture_output=True)
            
            return True
            
        except subprocess.CalledProcessError as e:
            logger.error(f"OCRmyPDF failed: {e.stderr.decode() if e.stderr else 'Unknown error'}")
            return False
        except Exception as e:
            logger.error(f"Error creating archival PDF: {e}")
            return False
        finally:
            import shutil
            if work_dir.exists():
                shutil.rmtree(work_dir, ignore_errors=True)
