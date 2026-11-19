from django.core.exceptions import BadRequest
from django.http import HttpResponseRedirect, JsonResponse, QueryDict
from django.shortcuts import resolve_url


# Redirecionamento 303: faz o navegador seguir o destino com GET após um PUT/DELETE
class HttpResponseSeeOther(HttpResponseRedirect):
    status_code = 303


# Informa se a requisição foi enviada pelo JavaScript da interface (app-ui.js)
def is_fetch_request(request):
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


# Lê os campos do formulário em POST (request.POST) ou em PUT/DELETE (corpo urlencoded)
def get_request_data(request):
    if request.method == 'POST':
        return request.POST
    if request.method in ('PUT', 'DELETE'):
        # Corpo vazio é válido (ex.: DELETE sem campos)
        if not request.body:
            return QueryDict('')
        # Com corpo, só aceitamos o mesmo formato que os formulários HTML enviam
        if request.content_type != 'application/x-www-form-urlencoded':
            raise BadRequest('Envie os dados como application/x-www-form-urlencoded.')
        return QueryDict(request.body, encoding=request.encoding)
    return QueryDict('')


# Redireciona após uma ação: JSON para o fetch da interface, 303/302 para os demais clientes
def redirect_after_action(request, to, *args, **kwargs):
    url = resolve_url(to, *args, **kwargs)
    # O fetch segue o redirecionamento sozinho e consumiria as mensagens; por isso devolvemos o destino em JSON
    if is_fetch_request(request):
        return JsonResponse({'redirect_url': url})
    if request.method in ('PUT', 'DELETE'):
        return HttpResponseSeeOther(url)
    return HttpResponseRedirect(url)
