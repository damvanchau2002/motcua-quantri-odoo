odoo.define('student_request.image_gallery', function (require) {
    'use strict';

    var FormController = require('web.FormController');
    var FormRenderer = require('web.FormRenderer');
    var core = require('web.core');

    FormRenderer.include({
        _renderView: function () {
            var self = this;
            return this._super.apply(this, arguments).then(function () {
                // Chỉ xử lý cho model student.service.request
                if (self.state.model === 'student.service.request') {
                    self._setupImageGallery();
                }
            });
        },

        _setupImageGallery: function () {
            var self = this;
            var $galleryContainer = this.$('.image_gallery');
            
            if ($galleryContainer.length === 0) {
                return;
            }

            // Lấy dữ liệu ảnh từ field image_attachment_ids
            var imageAttachmentIds = this.state.data.image_attachment_ids;
            
            if (!imageAttachmentIds || !imageAttachmentIds.data || imageAttachmentIds.data.length === 0) {
                $galleryContainer.html('<div class="image_gallery_empty">Không có ảnh đính kèm</div>');
                return;
            }

            $galleryContainer.html('<div class="image_gallery_loading">Đang tải ảnh...</div>');

            // Tạo gallery từ dữ liệu ảnh
            this._renderImageGallery(imageAttachmentIds.data, $galleryContainer);
        },

        _renderImageGallery: function (attachments, $container) {
            var self = this;
            var $gallery = $('<div class="image_gallery"></div>');

            attachments.forEach(function (attachment) {
                var attachmentId = attachment.id || attachment;
                var attachmentName = attachment.display_name || attachment.name || 'Ảnh đính kèm';
                
                // Tạo URL để hiển thị ảnh
                var imageUrl = '/web/image/' + attachmentId;
                var downloadUrl = '/web/content/' + attachmentId + '?download=true';
                
                var $imageItem = $('<div class="image_gallery_item"></div>');
                var $img = $('<img>').attr('src', imageUrl).attr('alt', attachmentName);
                var $overlay = $('<div class="image_overlay"><div class="image_name">' + attachmentName + '</div></div>');
                
                $imageItem.append($img);
                $imageItem.append($overlay);
                
                // Xử lý click để mở ảnh trong tab mới
                $imageItem.on('click', function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    
                    // Mở ảnh trong tab mới
                    window.open(imageUrl, '_blank');
                });

                // Xử lý lỗi load ảnh
                $img.on('error', function () {
                    $imageItem.html('<div class="image_overlay" style="opacity: 1;"><div class="image_name">Không thể tải ảnh<br>' + attachmentName + '</div></div>');
                });

                $gallery.append($imageItem);
            });

            $container.html($gallery);
        }
    });

    // Xử lý khi form được cập nhật
    FormController.include({
        _update: function () {
            var self = this;
            return this._super.apply(this, arguments).then(function () {
                if (self.modelName === 'student.service.request') {
                    // Đợi một chút để DOM được render xong
                    setTimeout(function () {
                        if (self.renderer && self.renderer._setupImageGallery) {
                            self.renderer._setupImageGallery();
                        }
                    }, 100);
                }
            });
        }
    });

    return {
        FormRenderer: FormRenderer,
        FormController: FormController
    };
});