
import os
import sys
from modules.preset_templates import DOCUMENT_PRESETS
from modules.docx_handler import DOCXHandler

def main():
    # Output directory
    output_dir = "output/generated_samples"
    os.makedirs(output_dir, exist_ok=True)

    # Initialize handler
    handler = DOCXHandler(output_dir=output_dir)

    print(f"Generating documents in {output_dir}...\n")

    for template_name, content in DOCUMENT_PRESETS.items():
        try:
            filename = f"{template_name}.docx"
            print(f"Creating {filename}...")
            
            # Use the template name as the title, or extract from content if possible
            # For simplicity, we use the template key as title context, 
            # but the content itself has the title in markdown ("# Title")
            
            # We pass the content directly. The DOCXHandler handles markdown parsing.
            file_path = handler.create_document(
                title=template_name.replace("_", " "),
                content=content,
                filename=filename
            )
            print(f"  -> Saved to: {file_path}")
        except Exception as e:
            print(f"  -> Error creating {template_name}: {e}")

    print("\nAll documents generated successfully.")

if __name__ == "__main__":
    main()

