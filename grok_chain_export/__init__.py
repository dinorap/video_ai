"""
Grok Video Chain - Module độc lập
==================================

Module này chứa toàn bộ chức năng tạo video Grok với frame chaining:
- Tạo video từ prompt và ảnh tham chiếu
- Cắt frame cuối của video để làm ảnh tham chiếu cho cảnh tiếp theo
- Hỗ trợ tạo chuỗi video liên tục với nhân vật/bối cảnh nhất quán

Cách sử dụng:
    from grok_chain_export import GrokVideoChain
    
    chain = GrokVideoChain(
        profile_dir="path/to/chrome/profile",
        output_dir="path/to/output"
    )
    
    await chain.create_video_chain(
        prompts=["cảnh 1", "cảnh 2", "cảnh 3"],
        first_image="path/to/first_image.jpg"
    )
"""

from .grok_chain import GrokVideoChain
from .frame_extractor import extract_last_frame, extract_first_frame

__version__ = "1.0.0"
__all__ = ["GrokVideoChain", "extract_last_frame", "extract_first_frame"]
