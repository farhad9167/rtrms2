"""
Full owner-dashboard translation for countries that need it.
Korean owners get the entire panel in Korean; everyone else (e.g. Bangladesh)
uses the English strings, since that's confirmed fine for them.

Usage in a route:
    from utils.admin_translations import get_admin_text
    atext = get_admin_text(restaurant.country_code)
    return render_template(..., atext=atext)

Usage in a template: {{ atext.orders }} instead of a hardcoded "Orders".
"""

ADMIN_FULLY_TRANSLATED_COUNTRIES = {"KR"}

EN = {
    "orders": "Orders", "menu": "Menu", "daily_offers": "Daily Offers",
    "settings": "Settings", "report": "Report", "subscription": "Subscription",
    "logout": "Logout", "table": "Table", "mode": "Mode", "items": "Items",
    "total": "Total", "status": "Status", "payment": "Payment", "action": "Action",
    "mark_paid": "Mark Paid", "no_orders": "No orders yet.", "auto_refresh": "Auto-refresh every 30s",
    "branding": "Branding", "bg_image": "Background Image (menu page)",
    "signboard_colors": "Signboard Colors", "popup_text": "Popup / Promo Text",
    "kitchen_printer": "Kitchen Printer Name", "counter_printer": "Counter Printer Name",
    "save_settings": "Save Settings", "admin_password": "Admin Login Password",
    "new_password": "New Password", "update_password": "Update Password",
    "add_category": "Add Category", "add_item": "Add Menu Item", "category": "Category",
    "name_primary": "Name (primary language)", "name_en": "Name (English)",
    "price": "Price", "image": "Image", "add": "Add",
    "current_menu": "Current Menu", "out_of_stock": "Out of Stock", "in_stock": "In Stock",
    "set_offer": "Set a Daily Offer", "menu_item": "Menu Item", "day": "Day",
    "every_day": "Every day", "discount_pct": "Discount %", "highlight_best_seller": "Highlight as Best Selling",
    "save_offer": "Save Offer", "active_offers": "Active Offers",
    "sub_status": "Status", "monthly_fee_for": "Monthly fee",
    "months_to_pay": "Months to pay for", "promo_code": "Promo code (optional)",
    "amount_due": "Amount due", "submit_verification": "Submit for Verification",
    "expiry_warning": "Your subscription expires in {days} day(s). Please renew to avoid interruption.",
    "tables_qr": "Tables & QR Codes", "table_count": "Number of Tables",
    "generate_qr": "Generate QR Codes", "gps_security": "Location Security",
    "gps_enable": "Require customers to be near the restaurant (GPS check)",
    "qr_expiry": "QR link expiry (minutes)", "staff": "Staff Accounts",
    "add_staff": "Add Staff", "staff_name": "Name", "staff_username": "Username",
    "staff_password": "Password", "staff_role": "Role", "sales_calendar": "Sales Calendar",
    "select_date": "Select a date", "best_sellers": "Best Sellers", "print_copy": "Print Copy",
    "leave_review": "Leave a Platform Review", "rating": "Rating", "review_text": "Your review",
    "submit_review": "Submit Review", "back_to_dashboard": "Back to Dashboard",
}

KR = {
    "orders": "주문", "menu": "메뉴 관리", "daily_offers": "오늘의 할인",
    "settings": "설정", "report": "리포트", "subscription": "구독 관리",
    "logout": "로그아웃", "table": "테이블", "mode": "이용 방식", "items": "품목",
    "total": "합계", "status": "상태", "payment": "결제", "action": "작업",
    "mark_paid": "결제 완료 처리", "no_orders": "아직 주문이 없습니다.", "auto_refresh": "30초마다 자동 새로고침",
    "branding": "브랜딩", "bg_image": "배경 이미지 (메뉴 페이지)",
    "signboard_colors": "간판 색상", "popup_text": "팝업 / 프로모션 문구",
    "kitchen_printer": "주방 프린터 이름", "counter_printer": "카운터 프린터 이름",
    "save_settings": "설정 저장", "admin_password": "관리자 로그인 비밀번호",
    "new_password": "새 비밀번호", "update_password": "비밀번호 변경",
    "add_category": "카테고리 추가", "add_item": "메뉴 항목 추가", "category": "카테고리",
    "name_primary": "이름 (한국어)", "name_en": "이름 (영어)",
    "price": "가격", "image": "이미지", "add": "추가",
    "current_menu": "현재 메뉴", "out_of_stock": "품절", "in_stock": "판매 중",
    "set_offer": "오늘의 할인 설정", "menu_item": "메뉴 항목", "day": "요일",
    "every_day": "매일", "discount_pct": "할인율 (%)", "highlight_best_seller": "베스트셀러로 표시",
    "save_offer": "할인 저장", "active_offers": "현재 할인 목록",
    "sub_status": "상태", "monthly_fee_for": "월 구독료",
    "months_to_pay": "결제할 개월 수", "promo_code": "프로모션 코드 (선택)",
    "amount_due": "결제 금액", "submit_verification": "결제 확인 요청",
    "expiry_warning": "구독이 {days}일 후 만료됩니다. 중단되지 않도록 갱신해 주세요.",
    "tables_qr": "테이블 & QR 코드", "table_count": "테이블 수",
    "generate_qr": "QR 코드 생성", "gps_security": "위치 보안",
    "gps_enable": "고객이 매장 근처에 있는지 확인 (GPS 체크)",
    "qr_expiry": "QR 링크 만료 시간 (분)", "staff": "직원 계정",
    "add_staff": "직원 추가", "staff_name": "이름", "staff_username": "아이디",
    "staff_password": "비밀번호", "staff_role": "역할", "sales_calendar": "매출 캘린더",
    "select_date": "날짜 선택", "best_sellers": "베스트셀러", "print_copy": "영수증 출력",
    "leave_review": "플랫폼 리뷰 남기기", "rating": "평점", "review_text": "리뷰 내용",
    "submit_review": "리뷰 제출", "back_to_dashboard": "대시보드로 돌아가기",
}


def get_admin_text(country_code, panel_language=None):
    """panel_language ('kr'/'en'), if explicitly set by the owner, always wins.
    Otherwise falls back to the old country-based default for restaurants
    that signed up before this setting existed."""
    if panel_language:
        return KR if panel_language == "kr" else EN
    if country_code in ADMIN_FULLY_TRANSLATED_COUNTRIES:
        return KR
    return EN
