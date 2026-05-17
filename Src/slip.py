import os
import shutil
import random

def split_yolo_dataset(source_dir, output_dir, split_ratio=0.8):
    # Kiểm tra xem thư mục nguồn có tồn tại không
    if not os.path.exists(source_dir):
        print(f"❌ Không tìm thấy thư mục nguồn: {source_dir}")
        return

    # Lấy danh sách tất cả các ảnh trực tiếp từ thư mục nguồn (hỗ trợ nhiều định dạng)
    valid_extensions = ('.bmp', '.jpg', '.jpeg', '.png')
    all_images = [f for f in os.listdir(source_dir) if f.lower().endswith(valid_extensions)]
    
    if len(all_images) == 0:
        print("❌ Không có ảnh nào trong thư mục!")
        return

    # Xáo trộn ảnh ngẫu nhiên để model học khách quan hơn
    random.shuffle(all_images)

    # Tính toán số lượng ảnh cho tập Train
    train_size = int(len(all_images) * split_ratio)
    train_images = all_images[:train_size]
    val_images = all_images[train_size:]

    # Tạo cấu trúc thư mục đích chuẩn của YOLO
    folders_to_create = [
        os.path.join(output_dir, "images", "train"),
        os.path.join(output_dir, "images", "val"),
        os.path.join(output_dir, "labels", "train"),
        os.path.join(output_dir, "labels", "val")
    ]
    for folder in folders_to_create:
        os.makedirs(folder, exist_ok=True)

    def copy_data(image_list, split_type):
        count = 0
        for img_name in image_list:
            # Tên file không có đuôi (để tìm file txt tương ứng)
            base_name = os.path.splitext(img_name)[0]
            txt_name = base_name + ".txt"

            # CHỈNH SỬA Ở ĐÂY: Cả ảnh và txt đều nằm chung trong source_dir
            img_src_path = os.path.join(source_dir, img_name)
            txt_src_path = os.path.join(source_dir, txt_name)

            # Chỉ copy nếu ảnh có file label đi kèm (hoặc bạn có thể cho phép copy cả ảnh không có lỗi)
            if os.path.exists(txt_src_path):
                # Copy ảnh
                shutil.copy(img_src_path, os.path.join(output_dir, "images", split_type, img_name))
                # Copy label
                shutil.copy(txt_src_path, os.path.join(output_dir, "labels", split_type, txt_name))
                count += 1
            else:
                # Dành cho trường hợp ảnh sạch (không có lỗi), YOLO có thể dùng file txt rỗng
                # Tự động tạo file txt rỗng nếu chưa có
                shutil.copy(img_src_path, os.path.join(output_dir, "images", split_type, img_name))
                open(os.path.join(output_dir, "labels", split_type, txt_name), 'a').close()
                count += 1
        return count

    print("⏳ Đang tiến hành chia dữ liệu từ thư mục hỗn hợp...")
    train_count = copy_data(train_images, "train")
    val_count = copy_data(val_images, "val")

    print("\n✅ CHIA DỮ LIỆU THÀNH CÔNG!")
    print(f"📁 Thư mục lưu trữ: {os.path.abspath(output_dir)}")
    print(f"📊 Tập Train: {train_count} ảnh")
    print(f"📊 Tập Val: {val_count} ảnh")

if __name__ == "__main__":
    # Nguồn: thư mục hỗn hợp hiện tại của bạn
    SOURCE_DIRECTORY = "D:\\Projects\\04_WafferDetection\\yolo_dataset" 
    # Đích: thư mục mới sẵn sàng cho YOLO
    OUTPUT_DIRECTORY = "D:\\Projects\\04_WafferDetection\\yolo_dataset_ready" 
    
    # Chia 80% Train, 20% Val
    split_yolo_dataset(SOURCE_DIRECTORY, OUTPUT_DIRECTORY, split_ratio=0.8)