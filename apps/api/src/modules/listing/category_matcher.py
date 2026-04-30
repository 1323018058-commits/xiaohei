from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

from .ai_service import ListingAiService
from .embedding_service import ListingEmbeddingService
from .repository import CATALOG_IMPORT_REQUIRED_MESSAGE, ListingCatalogRepository, ListingCatalogUnavailable


TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.IGNORECASE)
PATH_SPLIT_RE = re.compile(r"\s*(?:->|>|/|\\)\s*")

INTENT_SYNONYMS: dict[str, list[str]] = {
    "bluetooth_headset": [
        "蓝牙耳机",
        "无线耳机",
        "耳机",
        "bluetooth headset",
        "bluetooth headsets",
        "wireless headphones",
        "headphones",
        "headsets",
        "cellphone headsets",
    ],
    "plant_pot": [
        "花盆",
        "种植盆",
        "盆栽盆",
        "pots & planters",
        "plant pot",
        "plant pots",
        "flower pot",
        "flower pots",
        "planter",
        "planters",
    ],
    "dumbbell": [
        "哑铃",
        "健身哑铃",
        "dumbbell",
        "dumbbells",
        "free weights",
        "strength training",
    ],
    "pet_bed": [
        "宠物垫",
        "宠物床",
        "猫垫",
        "狗垫",
        "pet bed",
        "pet beds",
        "pet mat",
        "pet bedding",
        "pet beds & blankets",
    ],
    "bottle_warmer": [
        "奶瓶加热器",
        "温奶器",
        "暖奶器",
        "bottle warmer",
        "bottle warmers",
        "bottle warmers & sterilizers",
        "baby bottle warmer",
    ],
    "gloves": [
        "手套",
        "防护手套",
        "劳保手套",
        "glove",
        "gloves",
        "safety gloves",
        "protective gloves",
    ],
    "kitchen_storage": [
        "厨房收纳盒",
        "厨房收纳",
        "食物收纳盒",
        "保鲜盒",
        "food storage containers",
        "food storage",
        "storage containers",
        "kitchen organizers",
        "boxes & organisers",
    ],
    "phone_holder": [
        "车载手机支架",
        "手机支架",
        "手机架",
        "phone holder",
        "phone holders",
        "car phone holder",
        "motor vehicle interior accessories phone holders",
    ],
    "phone_case": [
        "手机壳",
        "手机套",
        "手机保护壳",
        "mobile phone case",
        "mobile phone cases",
        "phone case",
        "phone cases",
        "cellphone case",
        "cell phone case",
        "phone cover",
        "protective phone case",
        "mobile phone cover",
    ],
    "fishing_rod": [
        "鱼竿",
        "钓鱼竿",
        "路亚竿",
        "fishing rod",
        "fishing rods",
        "fishing pole",
        "fishing poles",
        "angling rod",
        "casting rod",
    ],
    "hammock": [
        "吊床",
        "户外吊床",
        "hammock",
        "hammocks",
        "camping hammock",
        "garden hammock",
    ],
    "camping_lantern": [
        "露营灯",
        "营地灯",
        "户外营地灯",
        "camping lantern",
        "camping lanterns",
        "camp lantern",
        "camping light",
        "camping lamp",
        "camping lamps",
        "lamp",
        "lamps",
        "lantern",
        "lanterns",
        "lamps & lanterns",
        "outdoor lantern",
        "portable lantern",
    ],
    "electric_toothbrush": [
        "电动牙刷",
        "electric toothbrush",
        "electric toothbrushes",
        "powered toothbrush",
        "sonic toothbrush",
        "rechargeable toothbrush",
    ],
    "screen_protector": [
        "手机膜",
        "钢化膜",
        "保护膜",
        "屏幕保护膜",
        "screen protector",
        "screen protectors",
        "electronics films",
        "films & shields",
    ],
    "power_bank": [
        "充电宝",
        "移动电源",
        "power bank",
        "power banks",
        "portable charger",
        "portable chargers",
    ],
    "charger": [
        "充电器",
        "充电头",
        "快充头",
        "charger",
        "chargers",
        "wall charger",
        "power adapter",
    ],
    "cable": [
        "数据线",
        "充电线",
        "usb线",
        "usb cable",
        "usb cables",
        "charging cable",
        "charging cables",
        "cables",
    ],
    "speaker": [
        "蓝牙音箱",
        "音箱",
        "音响",
        "speaker",
        "speakers",
        "bluetooth speaker",
        "portable speaker",
        "audio speaker",
    ],
    "backpack": [
        "背包",
        "双肩包",
        "书包",
        "backpack",
        "backpacks",
        "bags & cases",
    ],
    "yoga_mat": [
        "瑜伽垫",
        "健身垫",
        "yoga mat",
        "yoga mats",
        "fitness mat",
        "exercise mat",
        "yoga & pilates",
    ],
    "resistance_band": [
        "弹力带",
        "阻力带",
        "拉力带",
        "resistance band",
        "resistance bands",
        "strength training",
    ],
    "barbell": [
        "杠铃",
        "barbell",
        "barbells",
        "weight lifting",
        "strength training",
    ],
    "kettlebell": [
        "壶铃",
        "kettlebell",
        "kettlebells",
        "strength training",
    ],
    "water_bottle": [
        "水杯",
        "水壶",
        "运动水壶",
        "饮水瓶",
        "water bottle",
        "water bottles",
        "drinking bottle",
        "food & beverage carriers",
    ],
    "pet_toy": [
        "宠物玩具",
        "猫玩具",
        "狗玩具",
        "pet toy",
        "pet toys",
        "chew toys",
        "interactive toys",
        "pet toys & scratchers",
    ],
    "coffee_machine": [
        "咖啡机",
        "意式咖啡机",
        "coffee machine",
        "coffee machines",
        "espresso machine",
        "hot drink machines",
    ],
    "cooking_pot": [
        "锅",
        "汤锅",
        "炖锅",
        "煮锅",
        "铸铁锅",
        "pot",
        "pots",
        "potjie pot",
        "potjie pots",
        "cooking pots",
        "cookware",
        "braais accessories",
    ],
    "air_fryer": [
        "空气炸锅",
        "空气炸",
        "air fryer",
        "air fryers",
        "fryers",
        "kitchen appliances",
    ],
    "humidifier": [
        "加湿器",
        "空气加湿器",
        "humidifier",
        "humidifiers",
        "health equipment",
    ],
    "hair_dryer": [
        "吹风机",
        "电吹风",
        "hair dryer",
        "hair dryers",
        "hair styling tools",
    ],
    "keyboard": [
        "键盘",
        "电脑键盘",
        "keyboard",
        "keyboards",
        "input devices",
    ],
    "cat_litter_box": [
        "猫砂盆",
        "猫厕所",
        "cat litter box",
        "cat litter boxes",
        "litter boxes",
        "cat supplies",
    ],
    "umbrella": [
        "雨伞",
        "遮阳伞",
        "户外伞",
        "umbrella",
        "umbrellas",
        "outdoor umbrellas",
        "sunshades",
    ],
    "toy_car": [
        "玩具车",
        "儿童玩具车",
        "toy car",
        "toy cars",
        "play vehicles",
    ],
    "curtains": [
        "窗帘",
        "窗饰",
        "curtains",
        "curtains & drapes",
        "window treatments",
    ],
    "printer": [
        "打印机",
        "3d打印机",
        "printer",
        "printers",
        "3d printer",
        "3d printers",
        "print copy scan fax",
        "print, copy, scan & fax",
    ],
    "sofa_cover": [
        "沙发套",
        "沙发罩",
        "沙发保护套",
        "sofa cover",
        "sofa covers",
        "couch covers",
        "couch covers & protectors",
    ],
}

PREFERRED_CATEGORY_PHRASES: dict[str, list[str]] = {
    "bluetooth_headset": ["cellphone headsets", "headphones & headsets", "headsets", "standard headphones"],
    "plant_pot": ["pots & planters", "plant pots", "flower pots", "planters"],
    "dumbbell": ["dumbbells", "strength training", "free weights"],
    "pet_bed": ["pet beds & blankets", "pet beds", "pet bedding"],
    "bottle_warmer": ["bottle warmers & sterilizers", "bottle warmers", "bottle warmer"],
    "gloves": ["safety gloves", "gloves"],
    "kitchen_storage": ["food storage containers", "storage containers", "boxes & organisers", "kitchen organizers"],
    "phone_holder": ["phone holders", "phone holder"],
    "phone_case": ["mobile phone cases", "phone cases", "cellphone cases"],
    "fishing_rod": ["fishing rods", "fishing rod"],
    "hammock": ["hammocks", "hammock"],
    "camping_lantern": ["lamps & lanterns", "camping lanterns", "camping lantern", "lanterns"],
    "electric_toothbrush": ["electric toothbrushes", "electric toothbrush"],
    "screen_protector": ["screen protectors", "electronics films & shields", "films & shields"],
    "power_bank": ["power banks", "power bank"],
    "charger": ["chargers", "charger", "power adapters"],
    "cable": ["cables", "usb cables", "charging cables"],
    "speaker": ["speakers", "bluetooth speakers", "portable speakers"],
    "backpack": ["backpacks", "bags & cases"],
    "yoga_mat": ["yoga mats", "yoga & pilates", "exercise mats"],
    "resistance_band": ["resistance bands", "strength training"],
    "barbell": ["barbells", "strength training"],
    "kettlebell": ["kettlebells", "strength training"],
    "water_bottle": ["water bottles", "drinking bottle", "food & beverage carriers"],
    "pet_toy": ["pet toys & scratchers", "chew toys", "interactive toys", "pet toys"],
    "coffee_machine": ["coffee machines", "hot drink machines", "coffee machine"],
    "cooking_pot": ["potjie pots", "cooking pots", "pots", "cookware", "braais accessories"],
    "air_fryer": ["air fryers", "air fryer", "kitchen appliances"],
    "humidifier": ["humidifiers", "health equipment", "humidifier"],
    "hair_dryer": ["hair dryers", "hair styling tools & accessories", "hair dryer"],
    "keyboard": ["keyboards", "input devices", "keyboard"],
    "cat_litter_box": ["cat litter boxes", "cat supplies", "cat litter box"],
    "umbrella": ["outdoor umbrellas & sunshades", "umbrellas", "sunshades"],
    "toy_car": ["toy cars", "play vehicles"],
    "curtains": ["curtains & drapes", "window treatments", "curtains"],
    "printer": ["printers", "print, copy, scan & fax"],
    "sofa_cover": ["couch covers & protectors", "sofa accessories", "sofa covers"],
}

SEGMENT_TRANSLATIONS: dict[str, str] = {
    "audio devices": "音频设备",
    "audio accessories": "音频配件",
    "baby": "母婴",
    "baby food & nutrition": "婴儿食品与喂养",
    "bottle warmers & sterilizers": "奶瓶加热器与消毒器",
    "cellphone headsets": "手机耳机",
    "dumbbells": "哑铃",
    "electronic accessories": "电子配件",
    "family": "家庭",
    "food storage": "食物收纳",
    "food storage containers": "食物收纳盒",
    "garden, pool & patio": "花园泳池庭院",
    "gardening": "园艺",
    "headphones & headsets": "耳机与耳麦",
    "homeware: kitchen & decor": "厨具与家居装饰",
    "kitchen organizers": "厨房收纳",
    "lawn & garden": "草坪与园艺",
    "motor vehicle interior accessories": "汽车内饰配件",
    "pet beds & blankets": "宠物床垫与毯子",
    "pets": "宠物",
    "cat supplies": "猫用品",
    "cat litter boxes": "猫砂盆",
    "cat litter box": "猫砂盆",
    "litter boxes": "猫砂盆",
    "phone holders": "手机支架",
    "pots & planters": "花盆与种植盆",
    "safety gloves": "安全手套",
    "sport: equipment": "运动器材",
    "standard headphones": "标准耳机",
    "storage & organization": "收纳整理",
    "strength training": "力量训练",
    "mobile phone cases": "手机壳",
    "phone cases": "手机壳",
    "cellphone cases": "手机壳",
    "mobile phone covers": "手机壳",
    "fishing rods": "鱼竿",
    "fishing rod": "鱼竿",
    "hammocks": "吊床",
    "hammock": "吊床",
    "camping lanterns": "露营灯",
    "camping lantern": "露营灯",
    "electric toothbrushes": "电动牙刷",
    "electric toothbrush": "电动牙刷",
    "electronics": "电子产品",
    "consumer electronics": "电子产品",
    "electronic accessories": "电子配件",
    "mobile phone accessories": "手机配件",
    "cellphones": "手机",
    "cellphone accessories": "手机配件",
    "mobile phones": "手机",
    "accessories": "配件",
    "tv & audio": "电视与音频",
    "tv and audio": "电视与音频",
    "personal & lifestyle": "个人与生活方式",
    "personal and lifestyle": "个人与生活方式",
    "beauty": "美妆个护",
    "toothbrushes": "牙刷",
    "automotive": "汽车",
    "motor vehicle parts": "机动车配件",
    "small appliances": "小家电",
    "large appliances": "大家电",
    "kitchen appliances": "厨房电器",
    "braais & outdoor cooking": "烧烤与户外烹饪",
    "braais accessories": "烧烤配件",
    "potjie pots": "铸铁炖锅",
    "cooking pots": "锅具",
    "cookware": "锅具",
    "air fryers": "空气炸锅",
    "hot drink machines": "热饮机",
    "coffee machines": "咖啡机",
    "coffee machine parts & accessories": "咖啡机配件",
    "coffee, tea & espresso": "咖啡茶与意式咖啡",
    "office & business": "办公与商业",
    "industrial, business & scientific": "工业商业与科学用品",
    "print, copy, scan & fax": "打印复印扫描传真",
    "3d printers": "3D打印机",
    "3d printer": "3D打印机",
    "family": "家庭",
    "baby": "母婴",
    "baby health": "婴幼儿健康",
    "toys": "玩具",
    "play vehicles": "玩具车船飞机",
    "toy cars": "玩具汽车",
    "decor": "家居装饰",
    "window treatments": "窗帘窗饰",
    "curtains & drapes": "窗帘",
    "sofa accessories": "沙发配件",
    "couch covers & protectors": "沙发套与保护罩",
    "sofas": "沙发",
    "outdoor living": "户外生活",
    "outdoor umbrellas & sunshades": "户外遮阳伞与遮阳篷",
    "umbrellas": "雨伞",
    "sports": "运动",
    "sports & outdoor": "运动与户外",
    "sports and outdoor": "运动与户外",
    "outdoor": "户外",
    "camping": "露营",
    "fishing": "钓鱼",
    "garden": "花园",
    "patio": "庭院",
    "home": "家居",
    "health": "健康",
    "health equipment": "健康设备",
    "humidifiers": "加湿器",
    "personal care": "个人护理",
    "oral care": "口腔护理",
    "lighting": "照明",
    "lanterns": "灯具",
    "screen protectors": "屏幕保护膜",
    "electronics films & shields": "电子产品膜与保护",
    "films & shields": "膜与保护",
    "power banks": "充电宝",
    "chargers": "充电器",
    "cables": "线缆",
    "usb cables": "USB线缆",
    "speakers": "音箱",
    "bluetooth speakers": "蓝牙音箱",
    "portable speakers": "便携音箱",
    "bags & cases": "包袋与保护套",
    "backpacks": "背包",
    "yoga & pilates": "瑜伽与普拉提",
    "yoga mats": "瑜伽垫",
    "resistance bands": "弹力带",
    "barbells": "杠铃",
    "kettlebells": "壶铃",
    "food & beverage carriers": "食品饮料容器",
    "water bottles": "水杯水壶",
    "drinking bottle": "饮水瓶",
    "pet toys & scratchers": "宠物玩具与抓板",
    "chew toys": "咬胶玩具",
    "interactive toys": "互动玩具",
    "media": "媒体",
    "books": "图书",
    "books bisac": "图书分类",
    "consumables": "日用消耗品",
    "non perishable": "常温食品",
    "stationery": "文具",
    "diy": "DIY工具与家装",
    "sport: clothing & footwear": "运动服饰与鞋履",
    "fashion: clothing": "服装",
    "fashion: accessories": "时尚配饰",
    "fashion: footwear": "鞋履",
    "music": "音乐",
    "movies": "电影",
    "cameras": "相机",
    "office & office furniture": "办公与办公家具",
    "luggage": "箱包",
    "computer components": "电脑组件",
    "input devices": "输入设备",
    "keyboards": "键盘",
    "cycling": "骑行",
    "musical instruments": "乐器",
    "homeware: bed & bathroom": "床品与浴室用品",
    "arts & crafts": "美术与手工",
    "men": "男士",
    "women": "女士",
    "kids": "儿童",
    "kitchen tools & utensils": "厨房工具与用具",
    "computers & laptops": "电脑与笔记本",
    "general office supplies": "通用办公用品",
    "office equipment": "办公设备",
    "tableware": "餐具",
    "computer accessories": "电脑配件",
    "liquor": "酒类",
    "equipment": "设备",
    "footwear": "鞋履",
    "building materials": "建筑材料",
    "mom & baby care": "妈妈与宝宝护理",
    "household cleaning supplies": "家庭清洁用品",
    "gaming": "游戏",
    "household appliances": "家用电器",
    "food items": "食品",
    "wearable tech": "可穿戴设备",
    "handbags & wallets": "手提包与钱包",
    "camera parts & accessories": "相机零件与配件",
    "cookware & bakeware": "炊具与烘焙用具",
    "vehicle maintenance, care & decor": "车辆保养与装饰",
    "office furniture": "办公家具",
    "filing & organization": "文件归档与整理",
    "linens & bedding": "床上用品",
    "plumbing": "管道用品",
    "power tools": "电动工具",
    "gifting": "礼品",
    "christmas": "圣诞用品",
    "hair care": "护发",
    "hair styling tools & accessories": "美发工具及配件",
    "hair dryers": "吹风机",
    "laundry supplies": "洗衣用品",
    "golf": "高尔夫",
    "bathroom accessories": "浴室配件",
    "cabinets & storage": "柜类与收纳",
    "pet grooming supplies": "宠物美容用品",
    "swimming": "游泳",
    "kitchen appliance accessories": "厨房电器配件",
    "hand tools": "手动工具",
    "makeup": "彩妆",
    "work safety protective gear": "劳动安全防护用品",
}

INTENT_AVOID_TERMS: dict[str, list[str]] = {
    "bluetooth_headset": ["amplifier", "headphone amplifier", "guitar amps", "audio mixers", "earbud cases"],
    "dumbbell": ["supplement", "supplements", "nutrition", "protein", "amino acids", "creatine"],
    "phone_case": ["baby mobiles", "smartphones", "cellphone & sim card bundles"],
    "phone_holder": ["baby mobiles", "media", "books"],
    "plant_pot": ["books", "book", "bisac", "media", "sport", "stationery"],
    "screen_protector": ["phone cases", "cellphone cases", "camera screen protectors"],
    "power_bank": ["battery chargers", "camera chargers"],
    "speaker": ["computer speakers", "gaming speakers", "speaker stands", "books"],
    "backpack": ["camera backpacks", "laptop backpacks"],
    "yoga_mat": ["books", "yoga footwear", "exercise balls"],
    "pet_toy": ["pet beds", "pet bowls", "pet food"],
    "coffee_machine": ["coffee bags", "coffee beans", "coffee capsules", "coffee grinders", "machine parts"],
    "umbrella": ["umbrella accessories", "shade accessories", "shade cloths"],
    "toy_car": ["automotive", "car accessories", "media", "books"],
    "curtains": ["shower curtains", "curtain rods"],
    "printer": ["printer accessories", "printer replacement parts", "3d printer accessories"],
    "sofa_cover": ["sofas", "sleeper couches", "outdoor furniture covers"],
}

INTENT_SUPPRESSIONS: dict[str, list[str]] = {
    # "Power bank" often expands to "portable charger"; keep the more specific
    # product intent from being out-ranked by generic charger categories.
    "power_bank": ["charger"],
}

AI_RECALL_MIN_CANDIDATES = 12
AI_RERANK_CONFIDENCE_THRESHOLD = 0.9
AI_RERANK_CLOSE_MARGIN = 0.04
CATEGORY_MATCH_BUDGET_SECONDS = 2.8
AI_CATEGORY_CALL_TIMEOUT_SECONDS = 1.2
EMBEDDING_QUERY_TIMEOUT_SECONDS = 1.2


@dataclass
class CategoryMatchResult:
    suggestions: list[dict[str, Any]]
    total_candidates: int
    catalog_ready: bool
    ai_used: bool
    normalized_keywords: list[str]
    vector_used: bool = False
    vector_candidates: int = 0
    keyword_candidates: int = 0
    fuzzy_candidates: int = 0
    embedding_model: str | None = None
    embedding_dimensions: int | None = None
    translation_used: bool = False
    translation_model: str | None = None
    match_strategy: str = "keyword_rules"
    message: str | None = None


class CategoryMatcher:
    def __init__(
        self,
        *,
        repository: ListingCatalogRepository | None = None,
        ai_service: ListingAiService | None = None,
        embedding_service: ListingEmbeddingService | None = None,
    ) -> None:
        self.repository = repository or ListingCatalogRepository()
        self.ai_service = ai_service or ListingAiService()
        self.embedding_service = embedding_service or ListingEmbeddingService()

    def match(
        self,
        *,
        description: str,
        limit: int = 5,
        use_ai: bool = True,
    ) -> CategoryMatchResult:
        started_at = time.monotonic()
        keywords = self.normalize_keywords(description)
        avoid_keywords = self.avoid_keywords(description, keywords)
        local_intents = self._detect_intents([description, *keywords])
        ai_used = False
        keyword_candidates, catalog_ready = self.repository.recall_category_candidates(
            keywords=keywords,
            limit=max(50, limit * 10),
        )
        if (
            use_ai
            and self.ai_service.enabled
            and self._has_match_budget(started_at)
            and self._needs_ai_recall(keyword_candidates, limit)
            and not (local_intents and keyword_candidates)
        ):
            # Local rules and catalog substring recall are sub-100ms for common
            # Chinese categories. AI is reserved for low-recall searches so the
            # UI stays responsive without losing the long-tail semantic fallback.
            ai_keywords = self._call_with_budget(
                started_at=started_at,
                service=self.ai_service,
                timeout_seconds=AI_CATEGORY_CALL_TIMEOUT_SECONDS,
                fallback=[],
                callback=lambda: self.ai_service.extract_category_intent(description),
            )
            if ai_keywords:
                ai_used = True
                avoid_keywords = self._dedupe(
                    [
                        *avoid_keywords,
                        *[
                            value.removeprefix("avoid:").strip().lower()
                            for value in ai_keywords
                            if str(value).strip().lower().startswith("avoid:")
                        ],
                    ]
                )
                keywords = self._dedupe(
                    [
                        *keywords,
                        *self.expand_keywords(
                            [
                                value
                                for value in ai_keywords
                                if not str(value).strip().lower().startswith("avoid:")
                            ]
                        ),
                    ]
                )
                keyword_candidates, catalog_ready = self.repository.recall_category_candidates(
                    keywords=keywords,
                    limit=max(50, limit * 10),
                )
        fuzzy_candidates: list[dict[str, Any]] = []
        vector_candidates: list[dict[str, Any]] = []
        vector_used = False
        if use_ai and self.embedding_service.enabled and self._has_match_budget(started_at):
            # Embedding calls are useful only after the local catalog has been
            # vectorized. Checking the DB first avoids paying for a query vector
            # when there are no persisted Takealot category vectors to search.
            embedding_index_ready = self.repository.has_category_embeddings(
                embedding_model=self.embedding_service.model,
                embedding_dimensions=self.embedding_service.dimensions,
            )
            if embedding_index_ready:
                # Feed both the original Chinese text and AI-expanded English terms
                # into the embedding query. The vector index still returns only real
                # catalog rows; this just improves cross-language recall.
                embedding_query = "\n".join(self._dedupe([description, *keywords[:16]]))
                query_vector = self._call_with_budget(
                    started_at=started_at,
                    service=self.embedding_service,
                    timeout_seconds=EMBEDDING_QUERY_TIMEOUT_SECONDS,
                    fallback=[],
                    callback=lambda: self.embedding_service.embed_text(embedding_query),
                )
                if query_vector:
                    vector_candidates = self.repository.search_category_embeddings(
                        query_vector=query_vector,
                        embedding_model=self.embedding_service.model,
                        embedding_dimensions=self.embedding_service.dimensions,
                        top_k=50,
                        timeout_seconds=max(0.25, min(EMBEDDING_QUERY_TIMEOUT_SECONDS, self._remaining_match_budget(started_at) - 0.1)),
                    )
                    vector_used = bool(vector_candidates)

        if not catalog_ready:
            return CategoryMatchResult(
                suggestions=[],
                total_candidates=0,
                catalog_ready=False,
                ai_used=ai_used,
                normalized_keywords=keywords,
                vector_used=vector_used,
                vector_candidates=len(vector_candidates),
                keyword_candidates=len(keyword_candidates),
                embedding_model=self.embedding_service.model if self.embedding_service.enabled else None,
                embedding_dimensions=self.embedding_service.dimensions if self.embedding_service.enabled else None,
                fuzzy_candidates=0,
                match_strategy="keyword_rules",
                message=CATALOG_IMPORT_REQUIRED_MESSAGE,
            )
        # Exact keyword recall is fast, but Chinese inputs depend on AI-expanded
        # English terms and those terms are not always an exact substring of the
        # Takealot path. Fuzzy recall keeps recall broad while still returning
        # only category rows from the local catalog.
        if use_ai and self.ai_service.enabled and self._has_match_budget(started_at) and (
            not keyword_candidates or (ai_used and len(keyword_candidates) < max(20, limit * 4))
        ):
            try:
                fuzzy_candidates, fuzzy_catalog_ready = self.repository.fuzzy_recall_category_candidates(
                    keywords=keywords,
                    limit=max(160, limit * 32),
                )
                catalog_ready = catalog_ready or fuzzy_catalog_ready
            except ListingCatalogUnavailable:
                fuzzy_candidates = []
        candidates, candidate_sources = self._merge_candidates(
            keyword_candidates=keyword_candidates,
            fuzzy_candidates=fuzzy_candidates,
            vector_candidates=vector_candidates,
        )
        if not candidates:
            message = "No Takealot category candidates matched the description."
            if use_ai and self._contains_cjk(description):
                message = (
                    "中文泛品类需要 AI 翻译和类目向量索引兜底；"
                    "请配置 XH_AI_API_KEY 或 DASHSCOPE_API_KEY，并构建 Takealot 类目 embedding 后再匹配。"
                    if not self.ai_service.enabled or not self.embedding_service.enabled
                    else "AI 已启用，但当前类目库没有找到足够接近的候选；请尝试补充商品用途、材质或英文品类词。"
                )
            return CategoryMatchResult(
                suggestions=[],
                total_candidates=0,
                catalog_ready=True,
                ai_used=ai_used,
                normalized_keywords=keywords,
                vector_used=vector_used,
                vector_candidates=0,
                keyword_candidates=0,
                fuzzy_candidates=len(fuzzy_candidates),
                embedding_model=self.embedding_service.model if self.embedding_service.enabled else None,
                embedding_dimensions=self.embedding_service.dimensions if self.embedding_service.enabled else None,
                match_strategy="keyword_rules",
                message=message,
            )

        scored = self._score_and_dedupe(
            description=description,
            keywords=keywords,
            avoid_keywords=avoid_keywords,
            candidates=candidates,
            candidate_sources=candidate_sources,
        )
        ranked_ids: list[int] = []
        strong_local_winner = bool(local_intents and scored and float(scored[0].get("confidence") or 0) >= 0.9)
        if (
            use_ai
            and self.ai_service.enabled
            and self._has_match_budget(started_at)
            and not strong_local_winner
            and self._needs_ai_rerank(scored)
        ):
            # Reranking is a second model call. Skip it when the rule/vector
            # score already has a clear winner; keep it for ambiguous or weak
            # candidate sets where semantic judgment is worth the latency.
            ranked_ids = self._call_with_budget(
                started_at=started_at,
                service=self.ai_service,
                timeout_seconds=AI_CATEGORY_CALL_TIMEOUT_SECONDS,
                fallback=[],
                callback=lambda: self.ai_service.rerank_category_candidates(
                    description=description,
                    candidates=[item["category"] for item in scored[:20]],
                ),
            )
            ai_used = ai_used or bool(ranked_ids)

        if ranked_ids:
            rank_index = {category_id: index for index, category_id in enumerate(ranked_ids)}
            scored.sort(
                key=lambda item: (
                    1 if item["category"]["category_id"] in rank_index else 0,
                    -rank_index.get(item["category"]["category_id"], 999),
                    item["confidence"],
                ),
                reverse=True,
            )
            for item in scored:
                if item["category"]["category_id"] in rank_index:
                    item["source"] = self._append_source(item["source"], "ai")

        suggestions = [self._to_suggestion(item) for item in scored[:limit]]
        translation_used = False
        if use_ai and self.ai_service.enabled and self._has_match_budget(started_at):
            translation_used = self._apply_ai_path_translations(suggestions, started_at=started_at)
            ai_used = ai_used or translation_used
        fallback_warning = next(
            (
                str(candidate.get("vector_fallback_warning"))
                for candidate in vector_candidates
                if candidate.get("vector_fallback_warning")
            ),
            None,
        )
        match_strategy = "keyword_rules"
        if fuzzy_candidates:
            match_strategy = "keyword_fuzzy_rules"
        if vector_used:
            match_strategy = "keyword_fuzzy_vector_rules" if fuzzy_candidates else "keyword_vector_rules"
        if ranked_ids:
            match_strategy += "_ai_rerank"
        if translation_used:
            match_strategy += "_ai_translate"
        return CategoryMatchResult(
            suggestions=suggestions,
            total_candidates=len(candidates),
            catalog_ready=True,
            ai_used=ai_used,
            normalized_keywords=keywords,
            vector_used=vector_used,
            vector_candidates=len(vector_candidates),
            keyword_candidates=len(keyword_candidates),
            fuzzy_candidates=len(fuzzy_candidates),
            embedding_model=self.embedding_service.model if self.embedding_service.enabled else None,
            embedding_dimensions=self.embedding_service.dimensions if self.embedding_service.enabled else None,
            translation_used=translation_used,
            translation_model=getattr(self.ai_service, "model", None) if translation_used else None,
            match_strategy=match_strategy,
                message=fallback_warning,
        )

    def normalize_keywords(self, description: str) -> list[str]:
        tokens = [token.lower() for token in TOKEN_RE.findall(description or "")]
        return self.expand_keywords(tokens + [description])

    def avoid_keywords(self, description: str, keywords: list[str]) -> list[str]:
        intents = self._detect_intents([description, *keywords])
        values: list[str] = []
        for intent_key in intents:
            values.extend(INTENT_AVOID_TERMS.get(intent_key, []))
        return self._dedupe(values)

    def expand_keywords(self, values: list[str]) -> list[str]:
        haystack = " ".join(str(value or "").lower() for value in values)
        expanded: list[str] = []
        for token in values:
            normalized = str(token or "").strip().lower()
            if normalized:
                expanded.append(normalized)
        for intent_key, synonyms in INTENT_SYNONYMS.items():
            if any(synonym.lower() in haystack for synonym in synonyms):
                expanded.extend(synonyms)
                expanded.extend(PREFERRED_CATEGORY_PHRASES[intent_key])
        for token in list(expanded):
            if token.endswith(("shes", "ches")) and len(token) > 5:
                expanded.append(token[:-2])
            elif token.endswith("s") and len(token) > 4:
                expanded.append(token[:-1])
        return self._dedupe(expanded)

    def _merge_candidates(
        self,
        *,
        keyword_candidates: list[dict[str, Any]],
        fuzzy_candidates: list[dict[str, Any]],
        vector_candidates: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[int, set[str]]]:
        merged: dict[int, dict[str, Any]] = {}
        sources: dict[int, set[str]] = {}
        for source, candidates in (
            ("rules", keyword_candidates),
            ("fuzzy", fuzzy_candidates),
            ("vector", vector_candidates),
        ):
            for candidate in candidates:
                try:
                    category_id = int(candidate.get("category_id"))
                except (TypeError, ValueError):
                    continue
                sources.setdefault(category_id, set()).add(source)
                existing = merged.get(category_id)
                if existing is None:
                    merged[category_id] = dict(candidate)
                    continue
                if source == "fuzzy":
                    existing["fuzzy_score"] = candidate.get("fuzzy_score")
                if source == "vector":
                    existing["vector_similarity"] = candidate.get("vector_similarity")
                    existing["vector_rank"] = candidate.get("vector_rank")
                    existing["vector_embedding_model"] = candidate.get("vector_embedding_model")
                    existing["vector_embedding_dimensions"] = candidate.get("vector_embedding_dimensions")
                    existing["vector_embedding_hash"] = candidate.get("vector_embedding_hash")
        return list(merged.values()), sources

    def _score_and_dedupe(
        self,
        *,
        description: str,
        keywords: list[str],
        avoid_keywords: list[str],
        candidates: list[dict[str, Any]],
        candidate_sources: dict[int, set[str]],
    ) -> list[dict[str, Any]]:
        detected_intents = self._detect_intents([description, *keywords])
        best_by_category_id: dict[int, dict[str, Any]] = {}
        for candidate in candidates:
            score, matched_keywords, reasons = self._score_candidate(
                candidate=candidate,
                keywords=keywords,
                avoid_keywords=avoid_keywords,
                detected_intents=detected_intents,
            )
            category_id = int(candidate["category_id"])
            source_parts = candidate_sources.get(category_id) or {"rules"}
            vector_similarity = candidate.get("vector_similarity")
            if "vector" in source_parts and vector_similarity is not None and score >= 0.55:
                try:
                    vector_boost = min(0.06, max(0.0, float(vector_similarity) - 0.5) * 0.12)
                except (TypeError, ValueError):
                    vector_boost = 0.0
                if vector_boost > 0:
                    score = min(0.99, score + vector_boost)
                    reasons.append("vector candidate confirmed by rule context")
            fuzzy_score = candidate.get("fuzzy_score")
            if "fuzzy" in source_parts and fuzzy_score is not None:
                try:
                    fuzzy_value = float(fuzzy_score)
                except (TypeError, ValueError):
                    fuzzy_value = 0.0
                if fuzzy_value > 0.08:
                    score = max(score, min(0.74, 0.40 + fuzzy_value * 0.85))
                    if not matched_keywords:
                        matched_keywords.append("fuzzy catalog recall")
                    reasons.append("fuzzy catalog recall from AI-expanded terms")
            item = {
                "category": candidate,
                "confidence": score,
                "matched_keywords": matched_keywords,
                "match_reasons": reasons,
                "source": "+".join(part for part in ("rules", "fuzzy", "vector") if part in source_parts),
            }
            existing = best_by_category_id.get(category_id)
            if existing is None or item["confidence"] > existing["confidence"]:
                best_by_category_id[category_id] = item
        return sorted(
            best_by_category_id.values(),
            key=lambda item: (
                item["confidence"],
                len(item["matched_keywords"]),
                item["category"].get("min_required_images") or 0,
            ),
            reverse=True,
        )

    def _score_candidate(
        self,
        *,
        candidate: dict[str, Any],
        keywords: list[str],
        avoid_keywords: list[str],
        detected_intents: list[str],
    ) -> tuple[float, list[str], list[str]]:
        category_id = str(candidate.get("category_id") or "")
        leaf = str(candidate.get("lowest_category_name") or "").lower()
        main = str(candidate.get("main_category_name") or "").lower()
        department = str(candidate.get("department") or "").lower()
        path = self._path_en(candidate).lower()
        attribute_text = " ".join(
            self._attribute_terms(
                [
                    *(candidate.get("required_attributes") or []),
                    *(candidate.get("optional_attributes") or []),
                ]
            )
        ).lower()
        search_text = " ".join([leaf, main, department, path, attribute_text])
        score = 0.2
        matched_keywords: list[str] = []
        reasons: list[str] = []

        for intent_key in detected_intents:
            for phrase in PREFERRED_CATEGORY_PHRASES.get(intent_key, []):
                phrase_l = phrase.lower()
                if phrase_l == leaf or phrase_l in path:
                    score = max(score, 0.98)
                    matched_keywords.append(phrase_l)
                    reasons.append(f"preferred category phrase: {phrase}")

        for keyword in keywords:
            normalized = keyword.lower()
            if not normalized:
                continue
            if normalized == category_id:
                score = max(score, 1.0)
                matched_keywords.append(keyword)
                reasons.append("exact category_id match")
            elif normalized == leaf:
                score = max(score, 0.96)
                matched_keywords.append(keyword)
                reasons.append("exact lowest category name match")
            elif normalized in leaf:
                score = max(score, 0.86)
                matched_keywords.append(keyword)
                reasons.append("lowest category keyword match")
            elif normalized in path:
                score = max(score, 0.78)
                matched_keywords.append(keyword)
                reasons.append("category path keyword match")
            elif normalized in main:
                score = max(score, 0.68)
                matched_keywords.append(keyword)
                reasons.append("main category keyword match")
            elif normalized in department:
                score = max(score, 0.62)
                matched_keywords.append(keyword)
                reasons.append("department keyword match")
            elif normalized in search_text:
                score = max(score, 0.58)
                matched_keywords.append(keyword)
                reasons.append("catalog search text match")

        for avoid_keyword in avoid_keywords:
            normalized_avoid = avoid_keyword.lower().strip()
            if normalized_avoid and normalized_avoid in search_text:
                score = min(score, 0.35)
                reasons.append(f"avoid term matched: {avoid_keyword}")

        unique_matches = self._dedupe(matched_keywords)
        if len(unique_matches) >= 3:
            score = min(0.99, score + 0.04)
        return round(score, 4), unique_matches[:8], self._dedupe(reasons)[:5]

    def _to_suggestion(self, item: dict[str, Any]) -> dict[str, Any]:
        candidate = item["category"]
        return {
            "id": str(candidate.get("id") or candidate.get("category_id") or ""),
            "category_id": int(candidate["category_id"]),
            "path_en": self._path_en(candidate),
            "path_zh": self.path_zh(candidate),
            "confidence": item["confidence"],
            "min_required_images": int(candidate.get("min_required_images") or 0),
            "compliance_certificates": candidate.get("compliance_certificates") or [],
            "image_requirement_texts": candidate.get("image_requirement_texts") or [],
            "required_attributes": candidate.get("required_attributes") or [],
            "optional_attributes": candidate.get("optional_attributes") or [],
            "loadsheet_template_id": candidate.get("loadsheet_template_id"),
            "loadsheet_template_name": candidate.get("loadsheet_template_name") or "",
            "division": candidate.get("division") or "",
            "department": candidate.get("department") or "",
            "main_category_id": int(candidate.get("main_category_id") or 0),
            "main_category_name": candidate.get("main_category_name") or "",
            "lowest_category_name": candidate.get("lowest_category_name") or "",
            "lowest_category_raw": candidate.get("lowest_category_raw") or "",
            "attributes_ready": bool(candidate.get("attributes_ready")),
            "attribute_source": candidate.get("attribute_source") or "missing",
            "attribute_message": candidate.get("attribute_message"),
            "translation_source": "catalog" if candidate.get("path_zh") else "rules",
            "matched_keywords": item["matched_keywords"],
            "match_reasons": item["match_reasons"],
            "source": item["source"],
        }

    def _apply_ai_path_translations(self, suggestions: list[dict[str, Any]], *, started_at: float | None = None) -> bool:
        translate_paths = getattr(self.ai_service, "translate_category_paths", None)
        if not callable(translate_paths):
            return False
        if suggestions and not self._needs_ai_translation(suggestions[0]) and float(suggestions[0].get("confidence") or 0) >= 0.9:
            return False
        paths = [
            str(suggestion.get("path_en") or "").strip()
            for suggestion in suggestions
            if str(suggestion.get("path_en") or "").strip() and self._needs_ai_translation(suggestion)
        ]
        # Category matching is an interactive flow with a hard UI budget. AI
        # translation is display-only, so it must never delay returning a real
        # catalog category_id; if the budget is gone we keep the rule translation.
        if started_at is None:
            translations = translate_paths(paths)
        else:
            translations = self._call_with_budget(
                started_at=started_at,
                service=self.ai_service,
                timeout_seconds=AI_CATEGORY_CALL_TIMEOUT_SECONDS,
                fallback={},
                callback=lambda: translate_paths(paths),
            )
        if not translations:
            return False
        changed = False
        for suggestion in suggestions:
            path_en = str(suggestion.get("path_en") or "").strip()
            translated = translations.get(path_en)
            if not translated:
                continue
            # AI is allowed to improve display text only. category_id and all
            # matching decisions remain bound to the PostgreSQL catalog row.
            suggestion["path_zh"] = translated
            suggestion["translation_source"] = "ai"
            changed = True
        return changed

    @staticmethod
    def _needs_ai_recall(keyword_candidates: list[dict[str, Any]], limit: int) -> bool:
        return len(keyword_candidates) < max(AI_RECALL_MIN_CANDIDATES, limit * 3)

    @staticmethod
    def _remaining_match_budget(started_at: float) -> float:
        return CATEGORY_MATCH_BUDGET_SECONDS - (time.monotonic() - started_at)

    @classmethod
    def _has_match_budget(cls, started_at: float, minimum_seconds: float = 0.25) -> bool:
        return cls._remaining_match_budget(started_at) > minimum_seconds

    @classmethod
    def _call_with_budget(
        cls,
        *,
        started_at: float,
        service: Any,
        timeout_seconds: float,
        fallback: Any,
        callback: Any,
    ) -> Any:
        remaining = cls._remaining_match_budget(started_at)
        if remaining <= 0.25:
            return fallback
        previous_timeout = getattr(service, "timeout_seconds", None)
        if previous_timeout is not None:
            setattr(service, "timeout_seconds", max(0.25, min(float(previous_timeout), timeout_seconds, remaining - 0.1)))
        try:
            return callback()
        except Exception:
            return fallback
        finally:
            if previous_timeout is not None:
                setattr(service, "timeout_seconds", previous_timeout)

    @staticmethod
    def _needs_ai_rerank(scored: list[dict[str, Any]]) -> bool:
        if not scored:
            return False
        top_confidence = float(scored[0].get("confidence") or 0)
        if top_confidence < AI_RERANK_CONFIDENCE_THRESHOLD:
            return True
        if len(scored) < 2:
            return False
        second_confidence = float(scored[1].get("confidence") or 0)
        return (top_confidence - second_confidence) <= AI_RERANK_CLOSE_MARGIN

    @classmethod
    def _needs_ai_translation(cls, suggestion: dict[str, Any]) -> bool:
        path_zh = str(suggestion.get("path_zh") or "").strip()
        if not path_zh:
            return True
        # Rule translations cover common marketplace terms. Only call AI when a
        # segment is still mostly English, which keeps precise display text while
        # avoiding a model round trip for already translated paths.
        for segment in PATH_SPLIT_RE.split(path_zh):
            normalized = segment.strip()
            if normalized and not cls._contains_cjk(normalized) and re.search(r"[A-Za-z]", normalized):
                return True
        return False

    def path_zh(self, candidate: dict[str, Any]) -> str:
        existing = str(candidate.get("path_zh") or "").strip()
        if existing:
            return existing
        path_en = self._path_en(candidate)
        segments = [segment.strip() for segment in PATH_SPLIT_RE.split(path_en) if segment.strip()]
        if not segments:
            return ""
        return " > ".join(self.translate_segment(segment) for segment in segments)

    @staticmethod
    def translate_segment(segment: str) -> str:
        normalized = re.sub(r"\s+", " ", segment.strip().lower())
        if normalized in SEGMENT_TRANSLATIONS:
            return SEGMENT_TRANSLATIONS[normalized]
        for phrase, translated in sorted(SEGMENT_TRANSLATIONS.items(), key=lambda item: len(item[0]), reverse=True):
            if phrase in normalized:
                return translated
        return segment.strip()

    @classmethod
    def category_embedding_text(cls, candidate: dict[str, Any]) -> str:
        path_en = cls._path_en(candidate)
        path_zh = str(candidate.get("path_zh") or "").strip()
        if not path_zh and path_en:
            segments = [segment.strip() for segment in PATH_SPLIT_RE.split(path_en) if segment.strip()]
            path_zh = " > ".join(cls.translate_segment(segment) for segment in segments)
        parts = [
            str(candidate.get("division") or "").strip(),
            str(candidate.get("department") or "").strip(),
            str(candidate.get("main_category_name") or "").strip(),
            str(candidate.get("lowest_category_name") or "").strip(),
            path_en,
            path_zh,
            *cls._embedding_synonyms(candidate),
            *cls._attribute_terms(candidate.get("required_attributes") or []),
            *cls._attribute_terms(candidate.get("optional_attributes") or []),
        ]
        return "\n".join(cls._dedupe([part for part in parts if part]))

    @staticmethod
    def _path_en(candidate: dict[str, Any]) -> str:
        existing = str(candidate.get("path_en") or "").strip()
        if existing:
            return existing
        return " > ".join(
            part
            for part in [
                str(candidate.get("division") or "").strip(),
                str(candidate.get("department") or "").strip(),
                str(candidate.get("main_category_name") or "").strip(),
                str(candidate.get("lowest_category_name") or "").strip(),
            ]
            if part
        )

    @staticmethod
    def _detect_intents(values: list[str]) -> list[str]:
        haystack = " ".join(str(value or "").lower() for value in values)
        intents: list[str] = []
        for intent_key, synonyms in INTENT_SYNONYMS.items():
            if any(synonym.lower() in haystack for synonym in synonyms):
                intents.append(intent_key)
        intent_set = set(intents)
        for specific_intent, suppressed_intents in INTENT_SUPPRESSIONS.items():
            if specific_intent in intent_set:
                intents = [intent for intent in intents if intent not in suppressed_intents]
        return intents

    @classmethod
    def _embedding_synonyms(cls, candidate: dict[str, Any]) -> list[str]:
        haystack = " ".join(
            [
                cls._path_en(candidate).lower(),
                str(candidate.get("path_zh") or "").lower(),
                str(candidate.get("lowest_category_name") or "").lower(),
                str(candidate.get("main_category_name") or "").lower(),
            ]
        )
        values: list[str] = []
        for intent_key, synonyms in INTENT_SYNONYMS.items():
            preferred = PREFERRED_CATEGORY_PHRASES.get(intent_key, [])
            if any(phrase.lower() in haystack for phrase in [*synonyms, *preferred]):
                values.extend(synonyms)
                values.extend(preferred)
        return values

    @staticmethod
    def _attribute_terms(attributes: list[Any]) -> list[str]:
        terms: list[str] = []
        for item in attributes:
            if isinstance(item, str):
                terms.append(item)
                continue
            if not isinstance(item, dict):
                continue
            for key in ("key", "name", "attribute_key", "attribute_name", "field_name", "display_name", "label"):
                value = item.get(key)
                if value:
                    terms.append(str(value))
            options = item.get("options") or item.get("values") or item.get("allowed_values") or []
            if isinstance(options, list):
                for option in options[:12]:
                    if isinstance(option, dict):
                        option = option.get("value") or option.get("name") or option.get("label")
                    if option:
                        terms.append(str(option))
        return terms

    @staticmethod
    def _append_source(source: str, addition: str) -> str:
        parts = [part for part in source.split("+") if part]
        if addition not in parts:
            parts.append(addition)
        return "+".join(parts)

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            normalized = str(value or "").strip().lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result

    @staticmethod
    def _contains_cjk(value: str) -> bool:
        return bool(re.search(r"[\u4e00-\u9fff]", value or ""))
