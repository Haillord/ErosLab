"""
Публикация постов в группу ВКонтакте (фото и видео)
"""

import requests
import vk_api
import logging
from io import BytesIO

logger = logging.getLogger(__name__)

def post_to_vk(image_data, caption, media_url, group_id, token):
    """
    Публикует пост в группу ВКонтакте.
    """
    vk_session = vk_api.VkApi(token=token)
    vk = vk_session.get_api()

    url_lower = media_url.lower()
    is_video = url_lower.endswith(('.mp4', '.webm', '.gif'))

    if is_video:
        # 1. Получаем сервер для загрузки видео
        upload_data = vk.video.save(
            group_id=group_id,
            name=caption[:200],
            description="",
            is_private=0
        )
        upload_url = upload_data['upload_url']
        video_id = upload_data['video_id']
        owner_id = upload_data['owner_id']

        # 2. Загружаем видео
        files = {'video_file': ('video.mp4', BytesIO(image_data), 'video/mp4')}
        response = requests.post(upload_url, files=files).json()
        # Проверяем успешность (в ответе может быть размер и т.д.)
        if 'size' not in response:
            logger.error(f"Video upload failed: {response}")
            return

        attachment = f"video{owner_id}_{video_id}"
        logger.info(f"Video uploaded, attachment: {attachment}")
    else:
        # Фото: загружаем на стену
        upload_url = vk.photos.getWallUploadServer(group_id=group_id)['upload_url']
        files = {'photo': ('image.jpg', BytesIO(image_data), 'image/jpeg')}
        upload_response = requests.post(upload_url, files=files).json()

        photo = vk.photos.saveWallPhoto(
            group_id=group_id,
            photo=upload_response['photo'],
            server=upload_response['server'],
            hash=upload_response['hash']
        )[0]
        attachment = f"photo{photo['owner_id']}_{photo['id']}"

    # Публикуем пост на стене группы
    vk.wall.post(
        owner_id=-group_id,
        message=caption,
        attachments=attachment,
        signed=0  # от имени сообщества
    )
    logger.info("✅ Posted to VK")