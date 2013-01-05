import datetime
from tastypie.exceptions import BadRequest

from tastypie.resources import ALL, ALL_WITH_RELATIONS
from tastypie import fields
from tastypie.resources import ModelResource

from ..core.api import (ProductVersionResource, ProductResource,
                        MTAuthorization, MTApiKeyAuthentication)
from .models import CaseVersion, Case, Suite, CaseStep
from ..environments.api import EnvironmentResource
from ..tags.api import TagResource



class SuiteResource(ModelResource):

    product = fields.ToOneField(ProductResource, "product")

    class Meta:
        queryset = Suite.objects.all()
        fields = ["name", "product", "description", "status", "id"]
        list_allowed_methods = ["get", "post"]
        detail_allowed_methods = ["get", "put", "delete"]
        filtering = {
            "name": ALL,
            "product": ALL_WITH_RELATIONS,
            }
        authentication = MTApiKeyAuthentication()
        authorization = MTAuthorization()
        always_return_data = True


    def obj_create(self, bundle, request=None, **kwargs):
        """Set the created_by field for the suite to the request's user"""

        bundle = super(SuiteResource, self).obj_create(bundle=bundle, request=request, **kwargs)
        bundle.obj.created_by = request.user
        bundle.obj.save(user=request.user)
        return bundle


    def obj_update(self, bundle, request=None, **kwargs):
        """Set the modified_by field for the suite to the request's user"""

        bundle = super(SuiteResource, self).obj_update(bundle=bundle, request=request, **kwargs)
        bundle.obj.modified_on = datetime.datetime.utcnow()
        bundle.obj.save(user=request.user)
        return bundle


    def obj_delete(self, request=None, **kwargs):
        """Delete the object.
        The DELETE request may include permanent=True/False in its params parameter
        (ie, along with the user's credentials). Default is False.
        """
        permanent = request._request.dicts[1].get("permanent", False)
        # pull the id out of the request's path
        suite_id = request.path.split('/')[-2]
        suite = Suite.objects.get(id=suite_id)
        suite.delete(user=request.user, permanent=permanent)


    def delete_detail(self, request, **kwargs):
        """Avoid the following error:
        WSGIWarning: Content-Type header found in a 204 response, which not return content.
        """
        res = super(SuiteResource, self).delete_detail(request, **kwargs)
        del(res._headers["content-type"])
        return res



class CaseResource(ModelResource):
    suites = fields.ToManyField(SuiteResource, "suites", full=True)

    class Meta:
        queryset = Case.objects.all()
        fields= ["id", "suites"]
        filtering = {
            "suites": ALL_WITH_RELATIONS,
            }



class CaseStepResource(ModelResource):


    class Meta:
        queryset = CaseStep.objects.all()
        fields = ["instruction", "expected"]



class CaseVersionResource(ModelResource):

    case = fields.ForeignKey(CaseResource, "case", full=True)
    steps = fields.ToManyField(CaseStepResource, "steps", full=True)
    environments = fields.ToManyField(EnvironmentResource, "environments", full=True)
    productversion = fields.ForeignKey(ProductVersionResource, "productversion")
    tags = fields.ToManyField(TagResource, "tags", full=True)


    class Meta:
        queryset = CaseVersion.objects.all()
        list_allowed_methods = ['get']
        fields = ["id", "name", "description", "case"]
        filtering = {
            "environments": ALL,
            "productversion": ALL_WITH_RELATIONS,
            "case": ALL_WITH_RELATIONS,
            "tags": ALL_WITH_RELATIONS,
            }



class BaseSelectionResource(ModelResource):
    """Adds filtering by negation for use with multi-select widget"""
    #@@@ move this to mtapi.py when that code is merged in.

    def apply_filters(self, request, applicable_filters, applicable_excludes={}):
        """Apply included and excluded filters to query."""
        return self.get_object_list(request).filter(
            **applicable_filters).exclude(**applicable_excludes)


    def obj_get_list(self, request=None, **kwargs):
        """Return the list with included and excluded filters, if they exist."""
        filters = {}

        if hasattr(request, 'GET'): # pragma: no cover
            # Grab a mutable copy.
            filters = request.GET.copy()

        # Update with the provided kwargs.
        filters.update(kwargs)

        # Splitting out filtering and excluding items
        new_filters = {}
        excludes = {}
        for key, value in filters.items():
            # If the given key is filtered by ``not equal`` token, exclude it
            if key.endswith('__ne'):
                key = key[:-4] # Stripping out trailing ``__ne``
                excludes[key] = value
            else:
                new_filters[key] = value

        filters = new_filters

        # Building filters
        applicable_filters = self.build_filters(filters=filters)
        applicable_excludes = self.build_filters(filters=excludes)

        base_object_list = self.apply_filters(
            request, applicable_filters, applicable_excludes)
        return self.apply_authorization_limits(request, base_object_list)



class CaseSelectionResource(BaseSelectionResource):
    """
    Specialty end-point for an AJAX call in the Suite form multi-select widget
    for selecting cases.
    """

    case = fields.ForeignKey(CaseResource, "case")
    productversion = fields.ForeignKey(ProductVersionResource, "productversion")
    tags = fields.ToManyField(TagResource, "tags", full=True)

    class Meta:
        queryset = CaseVersion.objects.all().select_related(
            "case",
            "productversion",
            "created_by",
            ).prefetch_related(
                "tags",
                "case__suitecases",
                ).distinct().order_by("case__suitecases__order")
        list_allowed_methods = ['get']
        fields = ["id", "name", "latest"]
        filtering = {
            "productversion": ALL_WITH_RELATIONS,
            "tags": ALL_WITH_RELATIONS,
            "case": ALL_WITH_RELATIONS,
            "latest": ALL,
            }


    def dehydrate(self, bundle):
        """Add some convenience fields to the return JSON."""

        case = bundle.obj.case
        bundle.data["case_id"] = unicode(case.id)
        bundle.data["product_id"] = unicode(case.product_id)
        bundle.data["product"] = {"id": unicode(case.product_id)}

        try:
            bundle.data["created_by"] = {
                "id": unicode(bundle.obj.created_by.id),
                "username": bundle.obj.created_by.username,
                }
        except AttributeError:
            bundle.data["created_by"] = None

        if "case__suites" in bundle.request.GET.keys():
            suite_id=int(bundle.request.GET["case__suites"])
            order = [x.order for x in case.suitecases.all()
                if x.suite_id == suite_id][0]
            bundle.data["order"] = order
        else:
            bundle.data["order"] = None

        return bundle



class CaseVersionSelectionResource(BaseSelectionResource):
    """
    Specialty end-point for an AJAX call in the Tag form multi-select widget
    for selecting caseversions.
    """

    case = fields.ForeignKey(CaseResource, "case")
    productversion = fields.ForeignKey(ProductVersionResource, "productversion", full=True)
    tags = fields.ToManyField(TagResource, "tags", full=True)

    class Meta:
        queryset = CaseVersion.objects.all().select_related(
            "case",
            "productversion",
            "created_by",
            ).prefetch_related(
            "tags",
            )
        list_allowed_methods = ['get']
        fields = ["id", "name", "latest"]
        filtering = {
            "productversion": ALL_WITH_RELATIONS,
            "tags": ALL_WITH_RELATIONS,
            "case": ALL_WITH_RELATIONS,
            }


    def dehydrate(self, bundle):
        """Add some convenience fields to the return JSON."""

        case = bundle.obj.case
        bundle.data["case_id"] = unicode(case.id)
        bundle.data["product_id"] = unicode(case.product_id)
        bundle.data["product"] = {"id": unicode(case.product_id)}
        bundle.data["productversion_name"] = bundle.obj.productversion.name

        try:
            bundle.data["created_by"] = {
                "id": unicode(bundle.obj.created_by.id),
                "username": bundle.obj.created_by.username,
                }
        except AttributeError:
            bundle.data["created_by"] = None

        return bundle
