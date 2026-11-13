def compare_context(request):
    compare_list = request.session.get("compare_list", [])
    return {"compare_count": len(compare_list)}
